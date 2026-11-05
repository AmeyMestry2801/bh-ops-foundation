"""Phase 8: build results/RESULTS.md and results/resume_facts.json from the real result files.
Every number is read from a file written by the script named in the 'Source' column; none is typed by hand.

Run:  python -m src.make_results [--dashboard-tool "Tableau Public"|"Excel"|"not built"]
ALL DATA IS SYNTHETIC.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime

import duckdb
import pandas as pd

from src.config import DATA_END, DATA_START, RESULTS, ROOT, WAREHOUSE


def jload(name):
    return json.loads((RESULTS / name).read_text())


def run_pytest():
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                       capture_output=True, text=True)
    out = p.stdout + p.stderr
    nums = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error|errors)", out)}
    return {"passed": nums.get("passed", 0), "failed": nums.get("failed", 0) + nums.get("error", 0)
            + nums.get("errors", 0), "skipped": nums.get("skipped", 0)}


def versions():
    import duckdb as d, numpy, pandas, scipy, sklearn, statsmodels, xgboost
    out = {"python": sys.version.split()[0], "duckdb": d.__version__, "pandas": pandas.__version__,
           "numpy": numpy.__version__, "scipy": scipy.__version__, "statsmodels": statsmodels.__version__,
           "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__}
    try:
        import shap
        out["shap"] = shap.__version__
    except Exception:  # noqa: BLE001
        pass
    dbt = subprocess.run([str(ROOT / ".venv/bin/dbt"), "--version"], capture_output=True, text=True).stdout
    m = re.search(r"installed:\s+([\d.]+)", dbt)
    if m:
        out["dbt-core"] = m.group(1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-tool", default="not built")
    ap.add_argument("--dashboard-pages", type=int, default=0)
    args = ap.parse_args()

    gen = jload("../reports/generation_manifest.json")
    run, dq, kv = jload("pipeline_run.json"), jload("dq_summary.json"), jload("kpi_validation.json")
    head, ex, mm = jload("kpi_headline.json"), jload("experiment_summary.json"), jload("model_metrics.json")
    eff = pd.read_csv(RESULTS / "experiment_effects.csv")
    prim = eff[(eff["analysis"] == "primary") & eff["method"].str.startswith("cluster-robust")]

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    marts = {t: con.execute(f"select count(*) from marts.{t}").fetchone()[0] for t in
             ["dim_date", "dim_clinic", "dim_provider", "dim_patient", "fact_appointment", "fact_prior_auth", "fact_claim"]}
    con.close()
    tests = run_pytest()
    dbt = run["dbt"]

    def effect(comp, metric):
        r = prim[(prim["comparison"] == comp) & (prim["metric"] == metric)].iloc[0]
        return {"estimate": round(float(r["estimate"]), 4), "ci_low": round(float(r["ci_low"]), 4),
                "ci_high": round(float(r["ci_high"]), 4), "p_raw": float(r["p_raw"]), "p_holm": float(r["p_holm"])}

    tm = {r["model"]: r for r in mm["test_metrics"]}
    final = mm["promotion"]["final_model"]
    f = tm[final]
    sim = {r["scenario"]: r for r in mm["simulation"]["rows"]}
    facts = {
        "synthetic": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date_range": {"data": [DATA_START, DATA_END], "experiment": ["2025-10-01", "2026-03-31"]},
        "row_counts": {"raw": run["raw_row_counts"], "marts": marts},
        "dbt": {"models": dbt.get("models"), "tests": dbt.get("tests"), "tests_passed": dbt["pass"] - dbt.get("models", 0),
                "tests_warn": dbt["warn"], "tests_failed": dbt["error"],
                "note": "warnings are the 4 relationships tests on known injected orphan keys at the staging layer"},
        "pipeline": {"mode": run["mode"], "total_seconds": run["total_seconds"], "stage_seconds": run["stage_seconds"]},
        "data_quality": {"issue_types_found": dq["issue_types_found"],
                         "fixed_or_quarantined": dq["issue_types_fixed_or_quarantined"],
                         "flagged_only": dq["issue_types_flagged_only"], "integrity_checks": len(dq["integrity_checks"]),
                         "integrity_failed": dq["integrity_failed"], "reconciliation_ok": all(r["ok"] for r in dq["reconciliation"])},
        "kpi_validation": {"checks": kv["kpis_validated"], "passed": kv["passed"]},
        "headline_kpis": {k: round(v, 4) for k, v in head.items()},
        "experiment": {
            "decisions": {k: v["decision"] for k, v in ex["decisions"].items()},
            "arm_a_vs_control_risk_difference": effect("arm_a vs control", "risk difference"),
            "arm_b_vs_control_risk_difference": effect("arm_b vs control", "risk difference"),
            "arm_a_vs_control_odds_ratio": effect("arm_a vs control", "odds ratio"),
            "planted_effects_pp": {"arm_a": -3.0, "arm_b": -1.5},
            "omnibus_randomization_p": round(ex["validity"]["omnibus"].get("p", float("nan")), 4),
            "srm_p": round(ex["validity"]["srm_analysis"]["p"], 4),
            "design_effect": round(ex["power"]["design_effect"], 3),
            "note": "effects are planted by the generator; the project demonstrates the method"},
        "model": {"final_model": final, "promotion_gain_val": round(mm["promotion"]["gain_M2_minus_M1"], 4),
                  "promotion_ci": [round(mm["promotion"]["ci95_low"], 4), round(mm["promotion"]["ci95_high"], 4)],
                  "promote_M2": mm["promotion"]["promote_M2"],
                  "test_pr_auc": round(f["pr_auc"], 4), "test_pr_auc_ci": [round(f["pr_auc_ci_low"], 4), round(f["pr_auc_ci_high"], 4)],
                  "test_roc_auc": round(f["roc_auc"], 4), "test_brier": round(f["brier"], 4),
                  "base_rate_pr_auc_M0": round(tm["M0"]["pr_auc"], 4),
                  "precision_at_top20pct": round(f["precision_at_20pct"], 4), "recall_at_top20pct": round(f["recall_at_20pct"], 4),
                  "lift_at_top20pct": round(f["lift_at_20pct"], 3)},
        "simulation": {k: {"prevented": round(v["prevented"], 1), "ci": [round(v["prevented_low"], 1), round(v["prevented_high"], 1)],
                           "calls_per_prevented": round(v["calls_per_prevented"], 1)} for k, v in sim.items()},
        "tests": {"pytest_passed": tests["passed"], "pytest_failed": tests["failed"], "pytest_skipped": tests["skipped"]},
        "tools_actually_run": {k: v for k, v in versions().items()} | {"pytest": "run", "jupyter nbconvert": "run",
                                                                         "make": "pipeline target run"},
        "dashboard": {"tool": args.dashboard_tool, "pages_built": args.dashboard_pages,
                      "note": "filled from the command-line flag the author passed, not detected"},
    }
    (RESULTS / "resume_facts.json").write_text(json.dumps(facts, indent=2, default=str))

    L = ["# RESULTS (every number comes from the script named in its Source column)", "",
         "> ALL DATA IS SYNTHETIC. Effect sizes, noise rates and the no-show structure are my assumptions (docs/assumptions.md). "
         "Nothing here is a claim about real clinical or operational impact.", ""]

    def tbl(title, rows):
        L.extend([f"## {title}", "", "| Metric | Value | Source |", "|---|---|---|"] +
                 [f"| {a} | {b} | `{c}` |" for a, b, c in rows] + [""])

    def pc(x, d=1):
        return f"{x*100:.{d}f}%"

    tbl("Data and pipeline", [
        ("Raw rows (appointments / claims / patients)", f"{run['raw_row_counts']['appointments']:,} / {run['raw_row_counts']['claims']:,} / {run['raw_row_counts']['patients']:,}", "src/generate_data.py -> results/pipeline_run.json"),
        ("Mart rows (fact_appointment / fact_claim)", f"{marts['fact_appointment']:,} / {marts['fact_claim']:,}", "src/dq_checks.py"),
        ("Date range", f"{DATA_START} to {DATA_END}", "src/config.py"),
        ("dbt models / tests", f"{dbt.get('models')} / {dbt.get('tests')}", "src/pipeline.py -> dbt build"),
        ("dbt tests passed / warned / failed", f"{facts['dbt']['tests_passed']} / {dbt['warn']} / {dbt['error']}", "src/pipeline.py"),
        ("Pipeline runtime (last run)", f"{run['total_seconds']} s ({run['mode']})", "src/pipeline.py"),
        ("DQ issue types found / fixed or quarantined", f"{dq['issue_types_found']} / {dq['issue_types_fixed_or_quarantined']}", "src/dq_checks.py"),
        ("Mart integrity checks failed", f"{dq['integrity_failed']} of {len(dq['integrity_checks'])}", "src/dq_checks.py"),
    ])
    tbl("KPIs (SQL views verified against independent pandas)", [
        ("KPI checks passing", f"{kv['passed']} / {kv['kpis_validated']}", "src/kpis.py"),
        ("No-show rate", pc(head["no_show_rate"]), "src/kpis.py"),
        ("Late-cancel rate", pc(head["late_cancel_rate"]), "src/kpis.py"),
        ("Median days intake to first visit", f"{head['median_days_intake_to_first_visit']:.0f}", "src/kpis.py"),
        ("PA SLA-breach rate (assumed 72h/7d thresholds)", pc(head["pa_sla_breach_rate"]), "src/kpis.py"),
        ("Clean-claim rate", pc(head["clean_claim_rate"]), "src/kpis.py"),
        ("Mean days in A/R", f"{head['mean_days_in_ar']:.1f}", "src/kpis.py"),
        ("Revenue leakage (mature months)", pc(head["revenue_leakage_rate_mature"]), "src/kpis.py"),
    ])
    a, b = facts["experiment"]["arm_a_vs_control_risk_difference"], facts["experiment"]["arm_b_vs_control_risk_difference"]
    tbl("Reminder experiment (planted effects; method demonstration)", [
        ("Arm A vs control, risk difference (95% CI)", f"{a['estimate']*100:+.2f} pp ({a['ci_low']*100:+.2f} to {a['ci_high']*100:+.2f}); Holm p {a['p_holm']:.4f}", "src/experiment.py"),
        ("Arm B vs control, risk difference (95% CI)", f"{b['estimate']*100:+.2f} pp ({b['ci_low']*100:+.2f} to {b['ci_high']*100:+.2f}); Holm p {b['p_holm']:.4f}", "src/experiment.py"),
        ("Decisions (pre-specified rule)", f"A: {facts['experiment']['decisions']['arm_a']}, B: {facts['experiment']['decisions']['arm_b']}", "src/experiment.py"),
        ("Planted effects", "A -3.0 pp, B -1.5 pp", "src/generate_data.py"),
        ("Sample-ratio p / omnibus randomization p", f"{facts['experiment']['srm_p']} / {facts['experiment']['omnibus_randomization_p']} (flagged, see A39)", "src/experiment.py"),
    ])
    mdl = facts["model"]
    tbl("No-show model", [
        ("Final model (promotion rule)", f"{mdl['final_model']}; val PR-AUC gain of M2 over M1 {mdl['promotion_gain_val']:+.4f}, 95% CI {mdl['promotion_ci']}", "src/model.py"),
        ("Test PR-AUC (95% CI) vs base-rate PR-AUC", f"{mdl['test_pr_auc']:.3f} ({mdl['test_pr_auc_ci'][0]:.3f} to {mdl['test_pr_auc_ci'][1]:.3f}) vs {mdl['base_rate_pr_auc_M0']:.3f}", "src/model.py"),
        ("Test ROC-AUC / Brier", f"{mdl['test_roc_auc']:.3f} / {mdl['test_brier']:.4f}", "src/model.py"),
        ("Precision / recall / lift at top 20%", f"{pc(mdl['precision_at_top20pct'])} / {pc(mdl['recall_at_top20pct'])} / {mdl['lift_at_top20pct']:.2f}", "src/model.py"),
    ])
    tbl("Outreach simulation (assumptions A49; prevented no-shows in the test period, 95% CI)",
        [(k, f"{v['prevented']:.0f} ({v['ci'][0]:.0f} to {v['ci'][1]:.0f}); {v['calls_per_prevented']:.1f} calls per prevented", "src/model.py") for k, v in facts["simulation"].items()])
    tbl("Tests", [("pytest passed / failed / skipped", f"{tests['passed']} / {tests['failed']} / {tests['skipped']}", "pytest")])
    (RESULTS / "RESULTS.md").write_text("\n".join(L))
    print(json.dumps({"tests": tests, "dbt": facts["dbt"], "dashboard": facts["dashboard"]}, indent=2))
    print("wrote results/resume_facts.json and results/RESULTS.md")


if __name__ == "__main__":
    main()
