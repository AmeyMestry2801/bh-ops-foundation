"""Data-quality checks + row-count reconciliation (raw -> staging -> marts).

Run:  python -m src.dq_checks
Reads the warehouse read-only. Writes reports/dq_report.md and results/dq_summary.json.
Exit code 1 if reconciliation or mart-integrity checks fail.
ALL DATA IS SYNTHETIC.
"""
import json
import logging
import sys
from datetime import datetime

import duckdb

from src.config import REPORTS, RESULTS, WAREHOUSE

log = logging.getLogger("dq_checks")

# raw table, key column, staging model, mart model (None = not carried to a mart)
TABLES = [
    ("clinics", "clinic_id", "stg_clinics", "dim_clinic"),
    ("providers", "provider_id", "stg_providers", "dim_provider"),
    ("patients", "patient_id", "stg_patients", "dim_patient"),
    ("intake", "intake_id", "stg_intake", None),
    ("eligibility_checks", "eligibility_id", "stg_eligibility_checks", None),
    ("prior_authorizations", "pa_id", "stg_prior_authorizations", "fact_prior_auth"),
    ("appointments", "appointment_id", "stg_appointments", "fact_appointment"),
    ("claims", "claim_id", "stg_claims", "fact_claim"),
    ("experiment_assignments", "assignment_id", "stg_experiment_assignments", None),
]

APPT_OK = """(
    exists (select 1 from staging.stg_patients p
            where p.patient_id = {a}.patient_id and cast({a}.appt_ts as date) >= p.created_date)
    and exists (select 1 from staging.stg_providers v where v.provider_id = {a}.provider_id)
)"""

# Independently expressed (from staging) count of rows each mart SHOULD exclude.
EXPECTED_EXCLUSIONS = {
    "appointments": "select count(*) from staging.stg_appointments a where not " + APPT_OK.format(a="a"),
    "prior_authorizations": """select count(*) from staging.stg_prior_authorizations x
        where not exists (select 1 from staging.stg_patients p where p.patient_id = x.patient_id)""",
    "claims": """select count(*) from staging.stg_claims c
        where not exists (select 1 from staging.stg_appointments a
                          where a.appointment_id = c.appointment_id and """ + APPT_OK.format(a="a") + """)
           or c.paid_amount > c.allowed_amount or c.allowed_amount > c.billed_amount""",
}

# (issue, table, count SQL, handling text, category)  category: fixed | quarantined | flagged
ISSUES = [
    ("Duplicate rows", "patients",
     "select (select count(*) from raw.patients) - (select count(distinct patient_id) from raw.patients)",
     "Deduplicated in staging (keep first)", "fixed"),
    ("Duplicate rows", "eligibility_checks",
     "select (select count(*) from raw.eligibility_checks) - (select count(distinct eligibility_id) from raw.eligibility_checks)",
     "Deduplicated in staging", "fixed"),
    ("Duplicate rows", "appointments",
     "select (select count(*) from raw.appointments) - (select count(distinct appointment_id) from raw.appointments)",
     "Deduplicated in staging", "fixed"),
    ("Duplicate rows", "claims",
     "select (select count(*) from raw.claims) - (select count(distinct claim_id) from raw.claims)",
     "Deduplicated in staging", "fixed"),
    ("Payer spelling variants", "patients",
     "select count(*) from staging.stg_patients where payer_type_raw is not null "
     "and payer_type_raw not in ('Medicaid','Medicare','Commercial','Self-pay')",
     "Mapped to 4 canonical payer values", "fixed"),
    ("Missing payer", "patients",
     "select count(*) from staging.stg_patients where payer_type_raw is null",
     "Set to 'Unknown' (kept, flagged)", "flagged"),
    ("UTC-format timestamps", "appointments",
     "select count(*) from staging.stg_appointments where source_was_utc",
     "Converted to clinic-local time", "fixed"),
    ("Orphan patient_id", "appointments",
     "select count(*) from staging.stg_appointments a where not exists "
     "(select 1 from staging.stg_patients p where p.patient_id = a.patient_id)",
     "Excluded from fact_appointment", "quarantined"),
    ("Orphan provider_id", "appointments",
     "select count(*) from staging.stg_appointments a where not exists "
     "(select 1 from staging.stg_providers v where v.provider_id = a.provider_id)",
     "Excluded from fact_appointment", "quarantined"),
    ("Appointment before patient exists", "appointments",
     "select count(*) from staging.stg_appointments a join staging.stg_patients p on a.patient_id = p.patient_id "
     "where cast(a.appt_ts as date) < p.created_date",
     "Excluded from fact_appointment", "quarantined"),
    ("Orphan patient_id", "prior_authorizations",
     "select count(*) from staging.stg_prior_authorizations x where not exists "
     "(select 1 from staging.stg_patients p where p.patient_id = x.patient_id)",
     "Excluded from fact_prior_auth", "quarantined"),
    ("Orphan appointment_id", "claims",
     "select count(*) from staging.stg_claims c where not exists "
     "(select 1 from staging.stg_appointments a where a.appointment_id = c.appointment_id)",
     "Excluded from fact_claim", "quarantined"),
    ("paid_amount > allowed_amount", "claims",
     "select count(*) from staging.stg_claims where paid_amount > allowed_amount",
     "Excluded from fact_claim", "quarantined"),
    ("allowed_amount > billed_amount", "claims",
     "select count(*) from staging.stg_claims where allowed_amount > billed_amount",
     "Excluded from fact_claim", "quarantined"),
    ("Missing PHQ-9 total", "intake",
     "select count(*) from staging.stg_intake where phq9_total is null",
     "Left NULL (model handles missingness)", "flagged"),
    ("Missing GAD-7 total", "intake",
     "select count(*) from staging.stg_intake where gad7_total is null",
     "Left NULL (model handles missingness)", "flagged"),
]


def _fk(fact, col, dim, dim_col):
    return (f"select count(*) from marts.{fact} f left join marts.{dim} d "
            f"on f.{col} = d.{dim_col} where d.{dim_col} is null")


# (name, SQL returning a count that must be 0)
INTEGRITY = [
    ("fact_appointment duplicate keys", "select count(*) - count(distinct appointment_id) from marts.fact_appointment"),
    ("fact_claim duplicate keys", "select count(*) - count(distinct claim_id) from marts.fact_claim"),
    ("fact_prior_auth duplicate keys", "select count(*) - count(distinct pa_id) from marts.fact_prior_auth"),
    ("dim_patient duplicate keys", "select count(*) - count(distinct patient_id) from marts.dim_patient"),
    ("fact_appointment -> dim_patient orphans", _fk("fact_appointment", "patient_id", "dim_patient", "patient_id")),
    ("fact_appointment -> dim_provider orphans", _fk("fact_appointment", "provider_id", "dim_provider", "provider_id")),
    ("fact_appointment -> dim_date orphans", _fk("fact_appointment", "date_key", "dim_date", "date_key")),
    ("fact_claim -> fact_appointment orphans", _fk("fact_claim", "appointment_id", "fact_appointment", "appointment_id")),
    ("fact_claim -> dim_patient orphans", _fk("fact_claim", "patient_id", "dim_patient", "patient_id")),
    ("fact_prior_auth -> dim_patient orphans", _fk("fact_prior_auth", "patient_id", "dim_patient", "patient_id")),
    ("appointments before patient created",
     "select count(*) from marts.fact_appointment f join marts.dim_patient p on f.patient_id = p.patient_id "
     "where f.appt_date < p.created_date"),
    ("claims violating paid <= allowed <= billed",
     "select count(*) from marts.fact_claim where paid_amount > allowed_amount or allowed_amount > billed_amount"),
    ("prior auth decided before submitted",
     "select count(*) from marts.fact_prior_auth where decided_ts < submitted_ts"),
    ("negative lead_days", "select count(*) from marts.fact_appointment where lead_days < 0"),
]


def _scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def _md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return out


def run(dbt_summary: dict | None = None) -> dict:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)

    # ---- 1. reconciliation raw -> staging -> mart
    recon = []
    for raw_t, key, stg, mart in TABLES:
        raw_n = _scalar(con, f"select count(*) from raw.{raw_t}")
        distinct_n = _scalar(con, f"select count(distinct {key}) from raw.{raw_t}")
        stg_n = _scalar(con, f"select count(*) from staging.{stg}")
        mart_n = _scalar(con, f"select count(*) from marts.{mart}") if mart else None
        exp_ex = _scalar(con, EXPECTED_EXCLUSIONS[raw_t]) if raw_t in EXPECTED_EXCLUSIONS else 0
        dups_ok = (raw_n - stg_n) == (raw_n - distinct_n)
        mart_ok = True if mart is None else (stg_n - mart_n) == exp_ex
        recon.append({
            "table": raw_t, "raw": raw_n, "staging": stg_n, "mart": mart_n,
            "duplicates_removed": raw_n - stg_n, "expected_duplicates": raw_n - distinct_n,
            "mart_excluded": None if mart is None else stg_n - mart_n,
            "expected_mart_excluded": None if mart is None else exp_ex,
            "ok": bool(dups_ok and mart_ok),
        })

    # ---- 2. issues found / handled
    issues = []
    for name, table, sql, handling, cat in ISSUES:
        issues.append({"issue": name, "table": table, "rows": int(_scalar(con, sql)),
                       "handling": handling, "category": cat})

    # ---- 3. mart integrity (every count must be 0)
    integrity = [{"check": n, "violations": int(_scalar(con, s))} for n, s in INTEGRITY]

    dmin, dmax = con.execute("select min(appt_date), max(appt_date) from marts.fact_appointment").fetchone()
    con.close()

    recon_ok = all(r["ok"] for r in recon)
    integrity_failed = sum(1 for c in integrity if c["violations"] != 0)
    passed = recon_ok and integrity_failed == 0
    found = [i for i in issues if i["rows"] > 0]
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "reconciliation": recon,
        "issues": issues,
        "issue_types_found": len(found),
        "issue_types_fixed_or_quarantined": sum(1 for i in found if i["category"] in ("fixed", "quarantined")),
        "issue_types_flagged_only": sum(1 for i in found if i["category"] == "flagged"),
        "issue_rows_total_with_overlap": sum(i["rows"] for i in found),
        "integrity_checks": integrity,
        "integrity_failed": integrity_failed,
        "appt_date_range": [str(dmin), str(dmax)],
        "dbt": dbt_summary,
    }

    # ---- report
    L = ["# Data Quality Report", "",
         "> ALL DATA IS SYNTHETIC. Dirt was injected on purpose by src/generate_data.py.", "",
         f"Generated: {summary['generated_at']}  |  Overall: **{'PASS' if passed else 'FAIL'}**", ""]
    if dbt_summary:
        L += ["## dbt build", "", "`" + ", ".join(f"{k}={v}" for k, v in dbt_summary.items()) + "`", ""]
    L += ["## 1. Row-count reconciliation (raw -> staging -> mart)", ""]
    L += _md_table(
        ["table", "raw", "staging", "mart", "dups removed (expected)", "mart excluded (expected)", "ok"],
        [[r["table"], f"{r['raw']:,}", f"{r['staging']:,}",
          "-" if r["mart"] is None else f"{r['mart']:,}",
          f"{r['duplicates_removed']:,} ({r['expected_duplicates']:,})",
          "-" if r["mart_excluded"] is None else f"{r['mart_excluded']:,} ({r['expected_mart_excluded']:,})",
          "yes" if r["ok"] else "NO"] for r in recon])
    L += ["", "Every row dropped between layers is explained: duplicates (raw -> staging) and quarantined "
          "invalid rows (staging -> mart). 'Expected' is computed independently from staging.", "",
          "## 2. Issues found and how they were handled", ""]
    L += _md_table(["issue", "table", "rows", "handling", "category"],
                   [[i["issue"], i["table"], f"{i['rows']:,}", i["handling"], i["category"]] for i in issues])
    L += ["", f"Issue types found: {summary['issue_types_found']} "
          f"(fixed or quarantined: {summary['issue_types_fixed_or_quarantined']}, "
          f"flagged only: {summary['issue_types_flagged_only']}). "
          "Row counts can overlap across categories; do not sum them as unique rows.", "",
          "## 3. Mart integrity checks (all must be 0)", ""]
    L += _md_table(["check", "violations", "status"],
                   [[c["check"], c["violations"], "PASS" if c["violations"] == 0 else "FAIL"] for c in integrity])
    L += ["", f"Appointment date range in fact_appointment: {dmin} to {dmax}", ""]
    REPORTS.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "dq_report.md").write_text("\n".join(L))
    (RESULTS / "dq_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("DQ report written (%s)", "PASS" if passed else "FAIL")
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(0 if run()["passed"] else 1)
