"""Load raw CSVs into DuckDB schema `raw`, everything as VARCHAR.

Run:  python -m src.load_raw                  (full refresh)
      python -m src.load_raw --since 2026-04-01   (incremental for appointments + claims)

Incremental rule: for appointments (appt_ts) and claims (submit_date) delete raw rows whose
date text (first 10 chars) is >= --since and re-insert those rows from the CSV. Idempotent:
running it twice gives the same table. Late changes to rows older than --since are not seen.
All other tables are small and always fully reloaded.
"""
import argparse
import logging
import time
from datetime import datetime

import duckdb

from src.config import DATA_RAW, WAREHOUSE

TABLES = [
    "clinics", "providers", "patients", "intake", "eligibility_checks",
    "prior_authorizations", "appointments", "claims", "experiment_assignments",
]
INCREMENTAL = {"appointments": "appt_ts", "claims": "submit_date"}

log = logging.getLogger("load_raw")


def load_raw(since: str | None = None) -> dict:
    if since:
        datetime.strptime(since, "%Y-%m-%d")  # validate format
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    existing = {r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_schema = 'raw'").fetchall()}
    counts, modes = {}, {}
    for t in TABLES:
        path = DATA_RAW / f"{t}.csv"
        src = f"read_csv('{path}', header = true, all_varchar = true)"
        t0 = time.perf_counter()
        if since and t in INCREMENTAL and t in existing:
            col = INCREMENTAL[t]
            con.execute(f"DELETE FROM raw.{t} WHERE substr({col}, 1, 10) >= '{since}'")
            con.execute(f"""INSERT INTO raw.{t}
                            SELECT *, current_timestamp, '{path.name}' FROM {src}
                            WHERE substr({col}, 1, 10) >= '{since}'""")
            modes[t] = f"incremental(>={since})"
        else:
            con.execute(f"""CREATE OR REPLACE TABLE raw.{t} AS
                            SELECT *, current_timestamp AS _loaded_at, '{path.name}' AS _source_file
                            FROM {src}""")
            modes[t] = "full"
        n = con.execute(f"SELECT count(*) FROM raw.{t}").fetchone()[0]
        counts[t] = n
        log.info("raw.%-24s %9s rows  [%s]  (%.2fs)", t, f"{n:,}", modes[t], time.perf_counter() - t0)
    con.close()
    return {"counts": counts, "modes": modes}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None)
    load_raw(ap.parse_args().since)
