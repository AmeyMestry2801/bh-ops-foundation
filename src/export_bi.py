"""Phase 7: export BI-ready CSVs to bi/ for Tableau Public or Excel.

Run:  python -m src.export_bi     (after pipeline, kpis, experiment, model)
Reads the DuckDB marts (read-only) and results/. Writes bi/*.csv and results/bi_export.json.
Exit code 1 if any exported row count does not match its source.
ALL DATA IS SYNTHETIC. IDs only, no names.
"""
import json
import logging
import shutil
import sys

import duckdb
import numpy as np
import pandas as pd

from src.config import BI, RESULTS, WAREHOUSE

log = logging.getLogger("export_bi")

STAR = ["dim_date", "dim_clinic", "dim_provider", "dim_patient",
        "fact_appointment", "fact_prior_auth", "fact_claim"]
VIEWS = ["kpi_funnel", "kpi_gate_conversion", "kpi_prior_auth_monthly", "kpi_denials_by_reason"]
COPIES = ["experiment_results.csv", "experiment_arm_rates.csv", "experiment_guardrails.csv",
          "experiment_subgroups.csv", "lift_table.csv", "model_test_metrics.csv", "fairness_slices.csv"]
NEEDED = COPIES + ["model_scores.csv", "model_metrics.json", "dq_summary.json",
                   "pipeline_run.json", "kpi_validation.json"]
AR_FIRST_REPORTABLE = "2025-06"
NAME_COLUMNS = {"name", "first_name", "last_name", "patient_name", "full_name"}

FLAT_APPT = """
select f.appointment_id, f.patient_id, f.provider_id, f.clinic_id, f.appt_date, f.appt_ts,
       strftime(f.appt_date, '%Y-%m') as year_month, dayname(f.appt_date) as day_name,
       f.appt_dow, f.appt_hour, f.lead_days, f.lead_bucket, f.modality, f.status, f.reminder_arm,
       f.is_no_show, f.is_late_cancel, f.is_cancelled, f.is_completed, f.is_resolved,
       p.payer_type, p.age_band, p.language, p.prior_no_show_count, p.acuity, p.experiment_arm,
       v.provider_type, c.city as clinic_city, c.state as clinic_state
from marts.fact_appointment f
left join marts.dim_patient p on f.patient_id = p.patient_id
left join marts.dim_provider v on f.provider_id = v.provider_id
left join marts.dim_clinic c on f.clinic_id = c.clinic_id
"""


def n_rows(path):
    with open(path, "rb") as f:
        return sum(1 for _ in f) - 1


def col(df, x):
    if x is None:
        return np.full(len(df), np.nan)
    if isinstance(x, str):
        return pd.to_numeric(df[x]).to_numpy(dtype=float, na_value=np.nan)
    return np.asarray(x, dtype=float)


def build_kpi_monthly(con):
    parts = []

    def q(view):
        return con.execute(f"select * from marts.{view}").df()

    def add(df, kpi, value, basis, num=None, den=None, note="", ok=None):
        parts.append(pd.DataFrame({
            "year_month": df["year_month"].astype(str).to_numpy(),
            "kpi": kpi, "value": col(df, value), "numerator": col(df, num), "denominator": col(df, den),
            "month_basis": basis, "reportable": 1 if ok is None else np.asarray(ok, dtype=int), "note": note}))

    ap = q("kpi_appointments_monthly")
    add(ap, "no_show_rate", "no_show_rate", "appointment month", "no_shows", "resolved")
    add(ap, "late_cancel_rate", "late_cancel_rate", "appointment month", "late_cancels", "resolved")
    add(ap, "appointments_scheduled", "appointments_scheduled", "appointment month")

    fr = q("kpi_fill_rate_monthly")
    add(fr, "fill_rate", "fill_rate", "appointment month", "booked_slots", "capacity_slots",
        note="Capacity is an assumption (A21). 2025 is a synthetic ramp-up artifact (A27); only 2026 is reportable.",
        ok=(fr["year_month"] >= "2026-01"))

    cl = q("kpi_claims_monthly")
    for kpi, num in (("clean_claim_rate", "clean_claims"), ("first_pass_denial_rate", "first_pass_denials"),
                     ("final_denial_rate", "final_denials")):
        add(cl, kpi, kpi, "claim submission month", num, "claims_submitted")

    ar = q("kpi_ar_monthly")
    ok = ar["year_month"] >= AR_FIRST_REPORTABLE
    note = "Months before 2025-06 are biased low (claims start 2025-01; A51)."
    add(ar, "mean_days_in_ar", "mean_days_in_ar", "claim paid month", None, "paid_claims", note=note, ok=ok)
    add(ar, "median_days_in_ar", "median_days_in_ar", "claim paid month", None, "paid_claims", note=note, ok=ok)

    lk = q("kpi_leakage_monthly")
    add(lk, "revenue_leakage_rate", "leakage_rate", "claim submission month (through 2026-03)",
        lk["leaked_denied"] + lk["leaked_unpaid_90d"], "allowed_total",
        note="Only claims at least 90 days old at the data end date (A25).")

    pa = q("kpi_prior_auth_monthly")
    g = pa.groupby("year_month", as_index=False)[["decided", "sla_breaches"]].sum()
    g["rate"] = g["sla_breaches"] / g["decided"].where(g["decided"] > 0)
    add(g, "pa_sla_breach_rate", "rate", "prior-auth submission month", "sla_breaches", "decided",
        note="Decided requests only (A26). Thresholds are an assumption borrowed from CMS-0057-F.")

    ac = q("kpi_access_monthly")
    add(ac, "median_days_intake_to_first_visit", "median_days", "intake month", None, "patients_with_first_visit",
        note="Recent intake cohorts are right-censored (A28).")
    add(ac, "first_visit_rate", "first_visit_rate", "intake month", "patients_with_first_visit", "intakes")

    return pd.concat(parts, ignore_index=True).sort_values(["kpi", "year_month"]).reset_index(drop=True)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    missing = [str(RESULTS / f) for f in NEEDED if not (RESULTS / f).exists()]
    if missing:
        raise SystemExit("Missing inputs (run pipeline, kpis, experiment and model first):\n  " + "\n  ".join(missing))
    BI.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    expected = {}

    def export_sql(sql, name, expect):
        con.execute(f"COPY ({sql}) TO '{BI / name}' (HEADER, DELIMITER ',')")
        expected[name] = expect

    def export_df(df, name):
        df.to_csv(BI / name, index=False)
        expected[name] = len(df)

    for t in STAR:
        export_sql(f"select * from marts.{t}", f"{t}.csv", con.execute(f"select count(*) from marts.{t}").fetchone()[0])
    n_appt = con.execute("select count(*) from marts.fact_appointment").fetchone()[0]
    export_sql(FLAT_APPT, "appointment_flat.csv", n_appt)
    for v in VIEWS:
        export_sql(f"select * from marts.{v}", f"{v}.csv", con.execute(f"select count(*) from marts.{v}").fetchone()[0])

    export_df(build_kpi_monthly(con), "kpi_monthly.csv")

    n_scores = n_rows(RESULTS / "model_scores.csv")
    scores_path = RESULTS / "model_scores.csv"
    export_sql(f"""
        select s.appointment_id, s.patient_id, s.split, s.y_no_show, s.score_m0, s.score_m1, s.score_m2,
               s.score_final, cast(s.flagged_top20 as integer) as flagged_top20,
               f.appt_date, f.lead_bucket, f.modality, p.payer_type, p.age_band
        from read_csv('{scores_path}', header = true) s
        join marts.fact_appointment f on s.appointment_id = f.appointment_id
        join marts.dim_patient p on f.patient_id = p.patient_id""", "model_scores.csv", n_scores)
    con.close()

    for f in COPIES:
        shutil.copyfile(RESULTS / f, BI / f)
        expected[f] = n_rows(RESULTS / f)

    m = json.loads((RESULTS / "model_metrics.json").read_text())
    export_df(pd.DataFrame(m["simulation"]["rows"]), "outreach_simulation.csv")

    dq = json.loads((RESULTS / "dq_summary.json").read_text())
    export_df(pd.DataFrame(dq["reconciliation"]), "dq_reconciliation.csv")
    export_df(pd.DataFrame(dq["issues"]), "dq_issues.csv")
    integ = pd.DataFrame(dq["integrity_checks"])
    integ["status"] = np.where(integ["violations"] == 0, "PASS", "FAIL")
    export_df(integ, "dq_integrity.csv")

    run = json.loads((RESULTS / "pipeline_run.json").read_text())
    export_df(pd.DataFrame({"stage": list(run["stage_seconds"]), "seconds": list(run["stage_seconds"].values())}),
              "pipeline_stages.csv")
    summ = {"run_at": run["run_at"], "mode": run["mode"], "total_seconds": run["total_seconds"],
            **{f"dbt_{k}": v for k, v in run["dbt"].items()}, "dq_passed": run["dq_passed"],
            "dq_issue_types_found": run["dq_issue_types_found"], "dq_integrity_failed": run["dq_integrity_failed"]}
    export_df(pd.DataFrame({"metric": list(summ), "value": [str(v) for v in summ.values()]}), "pipeline_summary.csv")

    kv = json.loads((RESULTS / "kpi_validation.json").read_text())
    export_df(pd.DataFrame(kv["results"])[["kpi", "rows", "status"]], "kpi_validation.csv")

    # ---- verify
    files, bad = {}, []
    print("\n=== BI EXPORT (synthetic data) ===")
    for name in sorted(expected):
        n = n_rows(BI / name)
        cols = list(pd.read_csv(BI / name, nrows=1).columns)
        ok = expected[name] is None or n == expected[name]
        flagged = NAME_COLUMNS & {c.lower() for c in cols}
        if not ok or flagged:
            bad.append(name)
        files[name] = {"rows": n, "columns": len(cols)}
        print(f"  {'OK ' if ok and not flagged else 'BAD'} {name:32s} rows={n:>9,}  cols={len(cols)}")
    (RESULTS / "bi_export.json").write_text(json.dumps({"files": files, "all_ok": not bad}, indent=2))
    print(f"\n{len(files)} files in {BI}; row-count and name-column checks: {'PASS' if not bad else 'FAIL ' + str(bad)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
