"""Orchestrate: raw load -> dbt build (staging, marts, tests) -> DQ checks. Logs stage timings.

Run:
  python -m src.pipeline                      # full refresh of the raw layer
  python -m src.pipeline --since 2026-04-01   # incremental raw load for appointments/claims
dbt models are full-refresh tables (not dbt-incremental); only the raw load is incremental.
Writes results/pipeline_run.json and reports/dbt_build.log. ALL DATA IS SYNTHETIC.
"""
import argparse
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from src import dq_checks, load_raw
from src.config import REPORTS, RESULTS, ROOT

DBT_DIR = ROOT / "dbt_project"
log = logging.getLogger("pipeline")


def run_dbt() -> dict:
    exe = Path(sys.executable).parent / "dbt"
    cmd = [str(exe) if exe.exists() else "dbt", "build",
           "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=DBT_DIR)
    out = proc.stdout + proc.stderr
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "dbt_build.log").write_text(out)
    if proc.returncode != 0:
        log.error("dbt build FAILED. Last lines:\n%s", "\n".join(out.splitlines()[-40:]))
        raise SystemExit(1)
    done = re.search(r"Done\..*", out)
    summary = {k.lower().replace("-", "_"): int(v)
               for k, v in re.findall(r"([A-Z-]+)=(\d+)", done.group(0))} if done else {}
    m_tests = re.search(r"(\d+) data tests?", out)
    summary["models"] = sum(int(n) for n in re.findall(r"(\d+) (?:table|view) models?", out))
    if m_tests:
        summary["tests"] = int(m_tests.group(1))
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="YYYY-MM-DD: incremental raw load from this date")
    args = ap.parse_args()

    t_all = time.perf_counter()
    stages = {}

    t = time.perf_counter()
    loaded = load_raw.load_raw(since=args.since)
    stages["raw_load"] = round(time.perf_counter() - t, 2)
    log.info("stage raw_load done in %.2fs", stages["raw_load"])

    t = time.perf_counter()
    dbt = run_dbt()
    stages["dbt_build"] = round(time.perf_counter() - t, 2)
    log.info("stage dbt_build done in %.2fs  %s", stages["dbt_build"], dbt)

    t = time.perf_counter()
    dq = dq_checks.run(dbt_summary=dbt)
    stages["dq_checks"] = round(time.perf_counter() - t, 2)
    log.info("stage dq_checks done in %.2fs  passed=%s", stages["dq_checks"], dq["passed"])

    total = round(time.perf_counter() - t_all, 2)
    run_info = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "mode": f"incremental since {args.since}" if args.since else "full",
        "stage_seconds": stages,
        "total_seconds": total,
        "raw_row_counts": loaded["counts"],
        "raw_load_modes": loaded["modes"],
        "dbt": dbt,
        "dq_passed": dq["passed"],
        "dq_issue_types_found": dq["issue_types_found"],
        "dq_integrity_failed": dq["integrity_failed"],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "pipeline_run.json").write_text(json.dumps(run_info, indent=2))
    log.info("PIPELINE %s in %.2fs", "OK" if dq["passed"] else "FAILED DQ", total)
    if not dq["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
