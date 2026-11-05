"""Phase 3: validate the SQL KPI layer against an independent pandas recomputation.

Run:  python -m src.kpis        (after: python -m src.pipeline)
1. Reads the SQL KPI views (dbt models dbt_project/models/marts/kpi_*.sql).
2. Recomputes every KPI in pandas from the mart / staging tables.
3. Asserts equality (floats: rtol 1e-9). Writes results/kpi_*.csv, kpi_headline.json, kpi_validation.json.
Exit code 1 if any KPI mismatches. ALL DATA IS SYNTHETIC.
"""
import json
import logging
import sys

import duckdb
import numpy as np
import pandas as pd
import yaml

from src.config import RESULTS, ROOT, WAREHOUSE

log = logging.getLogger("kpis")

RESOLVED = ["completed", "no_show", "late_cancel"]
REASONS = {
    "CO-16": "Missing info / billing error",
    "CO-50": "Not medically necessary",
    "CO-27": "Coverage terminated",
    "CO-29": "Timely filing expired",
    "CO-4": "Procedure / modifier mismatch",
    "CO-18": "Duplicate claim",
    "CO-197": "Prior authorization absent",
}
VIEWS = [
    "kpi_appointments_monthly", "kpi_fill_rate_monthly", "kpi_patient_first_visit", "kpi_access_monthly",
    "kpi_funnel", "kpi_gate_conversion", "kpi_prior_auth_monthly", "kpi_claims_monthly",
    "kpi_denials_by_reason", "kpi_ar_monthly", "kpi_leakage_monthly",
]

HEADLINE_SQL = """
select
  (select cast(count(*) filter (where status = 'no_show') as double)
          / count(*) filter (where is_resolved = 1) from marts.fact_appointment) as no_show_rate,
  (select cast(count(*) filter (where status = 'late_cancel') as double)
          / count(*) filter (where is_resolved = 1) from marts.fact_appointment) as late_cancel_rate,
  (select avg(days_intake_to_first_visit) from marts.kpi_patient_first_visit) as mean_days_intake_to_first_visit,
  (select median(days_intake_to_first_visit) from marts.kpi_patient_first_visit) as median_days_intake_to_first_visit,
  (select cast(count(*) filter (where is_sla_breach = 1) as double) / count(decided_ts)
          from marts.fact_prior_auth) as pa_sla_breach_rate,
  (select median(turnaround_hours) from marts.fact_prior_auth) as pa_median_turnaround_hours,
  (select cast(count(*) filter (where denial_code is null) as double) / count(*)
          from marts.fact_claim) as clean_claim_rate,
  (select cast(count(*) filter (where denial_code is not null) as double) / count(*)
          from marts.fact_claim) as first_pass_denial_rate,
  (select avg(days_in_ar) from marts.fact_claim where claim_status = 'paid') as mean_days_in_ar,
  (select cast(sum(case when claim_status in ('denied', 'pending') then allowed_amount else 0 end) as double)
          / cast(sum(allowed_amount) as double)
   from marts.fact_claim where strftime(submit_date, '%Y-%m') <= '{max_month}') as revenue_leakage_rate_mature
"""


def load_vars():
    cfg = yaml.safe_load((ROOT / "dbt_project" / "dbt_project.yml").read_text())
    return float(cfg["vars"]["capacity_multiplier"]), str(cfg["vars"]["leakage_max_month"])


# ---------------------------------------------------------------- pandas recomputation
def pd_appointments(fa):
    d = pd.DataFrame({
        "year_month": fa["appt_date"].dt.strftime("%Y-%m"),
        "appointments_scheduled": 1,
        "resolved": fa["status"].isin(RESOLVED),
        "completed": fa["status"].eq("completed"),
        "no_shows": fa["status"].eq("no_show"),
        "late_cancels": fa["status"].eq("late_cancel"),
        "cancelled": fa["status"].eq("cancelled"),
    })
    out = d.groupby("year_month", as_index=False).sum()
    out["no_show_rate"] = out["no_shows"] / out["resolved"]
    out["late_cancel_rate"] = out["late_cancels"] / out["resolved"]
    return out


def pd_fill(fa, prov, mult):
    weekly = float(prov["weekly_slot_capacity"].sum()) * mult
    f2 = fa.assign(year_month=fa["appt_date"].dt.strftime("%Y-%m"))
    booked = f2[f2["status"] != "cancelled"].groupby("year_month").size().rename("booked_slots")
    dr = pd.date_range("2025-01-01", "2026-12-31", freq="D")
    days = pd.Series(dr.strftime("%Y-%m")).value_counts().rename("days_in_month").rename_axis("year_month")
    out = pd.concat([booked, days], axis=1, join="inner").reset_index()
    out["capacity_slots"] = weekly * out["days_in_month"] / 7.0
    out["fill_rate"] = out["booked_slots"] / out["capacity_slots"]
    return out[["year_month", "booked_slots", "capacity_slots", "fill_rate"]]


def pd_first_visit(dp, fa):
    comp = fa[fa["status"] == "completed"].groupby("patient_id")["appt_date"].min().rename("first_visit_date")
    p = dp[["patient_id", "intake_ts"]].merge(comp, on="patient_id", how="left")
    p["intake_date"] = p["intake_ts"].dt.normalize()
    p["days_intake_to_first_visit"] = (p["first_visit_date"] - p["intake_date"]).dt.days
    p["intake_month"] = p["intake_date"].dt.strftime("%Y-%m")
    g = p.groupby("intake_month")["days_intake_to_first_visit"]
    out = pd.DataFrame({
        "intakes": g.size(),
        "patients_with_first_visit": g.count(),
        "mean_days": g.mean(),
        "median_days": g.median(),
        "within14": g.apply(lambda s: int((s <= 14).sum())),
    }).rename_axis("year_month").reset_index()
    out["first_visit_rate"] = out["patients_with_first_visit"] / out["intakes"]
    out["pct_within_14d"] = out["within14"] / out["patients_with_first_visit"]
    return p, out.drop(columns="within14")


def pd_funnel(dp, fa, fc):
    names = ["Intake completed", "Appointment scheduled", "First visit completed", "Claim submitted", "Claim paid"]
    n = [
        dp["patient_id"].nunique(),
        fa["patient_id"].nunique(),
        fa.loc[fa["status"] == "completed", "patient_id"].nunique(),
        fc["patient_id"].nunique(),
        fc.loc[fc["claim_status"] == "paid", "patient_id"].nunique(),
    ]
    out = pd.DataFrame({"stage_order": [1, 2, 3, 4, 5], "stage": names, "patients": n})
    out["pct_of_intake"] = out["patients"] / out["patients"].iloc[0]
    out["pct_of_prev_stage"] = out["patients"] / out["patients"].shift(1)
    return out


def pd_gate(dp, fa, fpa, se):
    last = (se.sort_values(["checked_ts", "eligibility_id"]).groupby("patient_id").tail(1)
            [["patient_id", "eligibility_status"]])
    pa = (fpa.assign(d=(fpa["status"] == "denied").astype(int))
          .groupby("patient_id", as_index=False)["d"].max())
    b = dp[["patient_id"]].merge(last, on="patient_id", how="left").merge(pa, on="patient_id", how="left")
    b["eligibility_gate"] = np.where(b["eligibility_status"].isin(["inactive", "pending_info"]), "blocked", "clear")
    b["pa_gate"] = np.where(b["d"].isna(), "no_pa_needed", np.where(b["d"] == 1, "pa_denied", "pa_not_denied"))
    b["scheduled"] = b["patient_id"].isin(set(fa["patient_id"]))
    out = (b.groupby(["eligibility_gate", "pa_gate"])
           .agg(patients=("patient_id", "size"), scheduled_patients=("scheduled", "sum")).reset_index())
    out["scheduled_rate"] = out["scheduled_patients"] / out["patients"]
    return out


def pd_pa(fpa):
    hours = (fpa["decided_ts"] - fpa["submitted_ts"]).dt.total_seconds() / 3600.0
    thr = np.where(fpa["urgency"] == "urgent", 72, 168)
    dec = fpa["decided_ts"].notna()
    d = pd.DataFrame({
        "year_month": fpa["submitted_ts"].dt.strftime("%Y-%m"),
        "urgency": fpa["urgency"],
        "requests": 1,
        "decided": dec,
        "sla_breaches": (hours > thr) & dec,
        "denied": fpa["status"].eq("denied"),
        "hours": hours,
    })
    out = d.groupby(["year_month", "urgency"]).agg(
        requests=("requests", "sum"), decided=("decided", "sum"), sla_breaches=("sla_breaches", "sum"),
        denied=("denied", "sum"), mean_turnaround_hours=("hours", "mean"),
        median_turnaround_hours=("hours", "median")).reset_index()
    den = out["decided"].where(out["decided"] > 0)
    out["sla_breach_rate"] = out["sla_breaches"] / den
    out["denial_rate"] = out["denied"] / den
    return out


def pd_claims(fc):
    d = pd.DataFrame({
        "year_month": fc["submit_date"].dt.strftime("%Y-%m"),
        "claims_submitted": 1,
        "clean_claims": fc["denial_code"].isna(),
        "first_pass_denials": fc["denial_code"].notna(),
        "final_denials": fc["claim_status"].eq("denied"),
        "billed_total": fc["billed_amount"].astype(float),
        "allowed_total": fc["allowed_amount"].astype(float),
        "paid_total": fc["paid_amount"].astype(float),
    })
    out = d.groupby("year_month", as_index=False).sum()
    out["clean_claim_rate"] = out["clean_claims"] / out["claims_submitted"]
    out["first_pass_denial_rate"] = out["first_pass_denials"] / out["claims_submitted"]
    out["final_denial_rate"] = out["final_denials"] / out["claims_submitted"]
    return out


def pd_denials(fc, dp):
    c = fc.merge(dp[["patient_id", "payer_type"]], on="patient_id", how="inner")
    c["allowed_f"] = c["allowed_amount"].astype(float)
    tot = c.groupby("payer_type").size().rename("payer_claims").reset_index()
    den = (c[c["denial_code"].notna()].groupby(["payer_type", "denial_code"])
           .agg(denied_claims=("claim_id", "size"),
                recovered_claims=("claim_status", lambda s: int((s == "paid").sum())),
                allowed_amount_denied=("allowed_f", "sum")).reset_index())
    out = den.merge(tot, on="payer_type")
    out["denial_rate"] = out["denied_claims"] / out["payer_claims"]
    out["denial_reason"] = out["denial_code"].map(REASONS)
    return out


def pd_ar(fc):
    p = fc[(fc["claim_status"] == "paid") & fc["paid_date"].notna()].copy()
    p["days"] = (p["paid_date"] - p["submit_date"]).dt.days
    p["year_month"] = p["paid_date"].dt.strftime("%Y-%m")
    g = p.groupby("year_month")["days"]
    return pd.DataFrame({"paid_claims": g.size(), "mean_days_in_ar": g.mean(),
                         "median_days_in_ar": g.median()}).reset_index()


def pd_leakage(fc, max_month):
    d = fc.assign(year_month=fc["submit_date"].dt.strftime("%Y-%m"), allowed=fc["allowed_amount"].astype(float))
    d = d[d["year_month"] <= max_month].copy()
    d["leaked_denied"] = np.where(d["claim_status"] == "denied", d["allowed"], 0.0)
    d["leaked_unpaid_90d"] = np.where(d["claim_status"] == "pending", d["allowed"], 0.0)
    out = d.groupby("year_month").agg(
        claims=("claim_id", "size"), allowed_total=("allowed", "sum"),
        leaked_denied=("leaked_denied", "sum"), leaked_unpaid_90d=("leaked_unpaid_90d", "sum")).reset_index()
    out["leakage_rate"] = (out["leaked_denied"] + out["leaked_unpaid_90d"]) / out["allowed_total"]
    return out


def pd_headline(fa, fc, fpa, p, max_month):
    resolved = fa["status"].isin(RESOLVED).sum()
    hours = (fpa["decided_ts"] - fpa["submitted_ts"]).dt.total_seconds() / 3600.0
    thr = np.where(fpa["urgency"] == "urgent", 72, 168)
    dec = fpa["decided_ts"].notna()
    paid = fc[fc["claim_status"] == "paid"]
    ar = (paid["paid_date"] - paid["submit_date"]).dt.days
    mature = fc[fc["submit_date"].dt.strftime("%Y-%m") <= max_month]
    allowed = mature["allowed_amount"].astype(float)
    leaked = allowed[mature["claim_status"].isin(["denied", "pending"])].sum()
    return {
        "no_show_rate": float((fa["status"] == "no_show").sum() / resolved),
        "late_cancel_rate": float((fa["status"] == "late_cancel").sum() / resolved),
        "mean_days_intake_to_first_visit": float(p["days_intake_to_first_visit"].mean()),
        "median_days_intake_to_first_visit": float(p["days_intake_to_first_visit"].median()),
        "pa_sla_breach_rate": float(((hours > thr) & dec).sum() / dec.sum()),
        "pa_median_turnaround_hours": float(hours.median()),
        "clean_claim_rate": float(fc["denial_code"].isna().mean()),
        "first_pass_denial_rate": float(fc["denial_code"].notna().mean()),
        "mean_days_in_ar": float(ar.mean()),
        "revenue_leakage_rate_mature": float(leaked / allowed.sum()),
    }


# ---------------------------------------------------------------- comparison
def compare(name, sql_df, pd_df, keys):
    try:
        a = sql_df.sort_values(keys).reset_index(drop=True)
        b = pd_df.sort_values(keys).reset_index(drop=True)
        if set(a.columns) != set(b.columns):
            raise AssertionError(f"column mismatch: sql-only={set(a.columns) - set(b.columns)} "
                                 f"pandas-only={set(b.columns) - set(a.columns)}")
        b = b[list(a.columns)]
        # nullable Int64 (pd.NA) and float64 (NaN) are unequal to assert_frame_equal; align numerics
        for c in a.columns:
            if pd.api.types.is_numeric_dtype(a[c]) and not pd.api.types.is_bool_dtype(a[c]):
                a[c] = a[c].astype("float64")
                b[c] = b[c].astype("float64")
        pd.testing.assert_frame_equal(a, b, check_dtype=False, rtol=1e-9, atol=1e-9)
        return {"kpi": name, "rows": int(len(a)), "status": "PASS", "detail": ""}
    except Exception as e:  # noqa: BLE001
        return {"kpi": name, "rows": int(len(sql_df)), "status": "FAIL", "detail": str(e)[:700]}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mult, max_month = load_vars()
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    sqlv = {v: con.execute(f"select * from marts.{v}").df() for v in VIEWS}
    fa = con.execute("select * from marts.fact_appointment").df()
    fc = con.execute("select * from marts.fact_claim").df()
    fpa = con.execute("select * from marts.fact_prior_auth").df()
    dp = con.execute("select * from marts.dim_patient").df()
    prov = con.execute("select * from marts.dim_provider").df()
    se = con.execute("select eligibility_id, patient_id, checked_ts, eligibility_status "
                     "from staging.stg_eligibility_checks").df()
    head_sql = con.execute(HEADLINE_SQL.format(max_month=max_month)).df().iloc[0].to_dict()
    con.close()

    # sanity: empty strings must have been read as NULL
    if (fc["denial_code"] == "").any():
        raise SystemExit("denial_code contains empty strings; staging should map them to NULL")

    p, access = pd_first_visit(dp, fa)
    results = [
        compare("no-show / late-cancel (monthly)", sqlv["kpi_appointments_monthly"], pd_appointments(fa), ["year_month"]),
        compare("fill rate (monthly)", sqlv["kpi_fill_rate_monthly"], pd_fill(fa, prov, mult), ["year_month"]),
        compare("intake -> first visit (per patient)",
                sqlv["kpi_patient_first_visit"][["patient_id", "days_intake_to_first_visit"]],
                p[["patient_id", "days_intake_to_first_visit"]], ["patient_id"]),
        compare("intake -> first visit (monthly)", sqlv["kpi_access_monthly"], access, ["year_month"]),
        compare("patient funnel", sqlv["kpi_funnel"], pd_funnel(dp, fa, fc), ["stage_order"]),
        compare("gate conversion", sqlv["kpi_gate_conversion"], pd_gate(dp, fa, fpa, se),
                ["eligibility_gate", "pa_gate"]),
        compare("prior-auth turnaround / SLA (monthly)", sqlv["kpi_prior_auth_monthly"], pd_pa(fpa),
                ["year_month", "urgency"]),
        compare("clean-claim / denial (monthly)", sqlv["kpi_claims_monthly"], pd_claims(fc), ["year_month"]),
        compare("denials by reason and payer", sqlv["kpi_denials_by_reason"], pd_denials(fc, dp),
                ["payer_type", "denial_code"]),
        compare("days in A/R (monthly)", sqlv["kpi_ar_monthly"], pd_ar(fc), ["year_month"]),
        compare("revenue leakage (monthly)", sqlv["kpi_leakage_monthly"], pd_leakage(fc, max_month), ["year_month"]),
    ]
    head_pd = pd_headline(fa, fc, fpa, p, max_month)
    for k, v in head_sql.items():
        ok = bool(np.isclose(float(v), head_pd[k], rtol=1e-9, atol=1e-12))
        results.append({"kpi": f"headline: {k}", "rows": 1, "status": "PASS" if ok else "FAIL",
                        "detail": "" if ok else f"sql={v} pandas={head_pd[k]}"})

    RESULTS.mkdir(parents=True, exist_ok=True)
    for name, df in sqlv.items():
        if name != "kpi_patient_first_visit":
            df.to_csv(RESULTS / f"{name}.csv", index=False)
    headline = {k: float(v) for k, v in head_sql.items()}
    (RESULTS / "kpi_headline.json").write_text(json.dumps(headline, indent=2))
    n_pass = sum(r["status"] == "PASS" for r in results)
    (RESULTS / "kpi_validation.json").write_text(json.dumps(
        {"kpis_validated": len(results), "passed": n_pass, "capacity_multiplier": mult,
         "leakage_max_month": max_month, "results": results}, indent=2))

    print("\n=== KPI VALIDATION: SQL view vs independent pandas ===")
    for r in results:
        print(f"  {r['status']}  {r['kpi']:46s} rows={r['rows']}")
        if r["detail"]:
            print("      ", r["detail"])
    print(f"\n{n_pass}/{len(results)} checks passed")

    print("\n=== HEADLINE KPIs (synthetic data) ===")
    for k, v in headline.items():
        print(f"  {k:36s} {v:,.4f}")

    print(f"\n=== FILL RATE BY MONTH (capacity_multiplier={mult}) ===")
    print(sqlv["kpi_fill_rate_monthly"].round(3).to_string(index=False))
    print("\n=== PATIENT FUNNEL ===")
    print(sqlv["kpi_funnel"].round(3).to_string(index=False))
    print("\n=== WHERE PATIENTS DROP OUT (share ever scheduled, by gate) ===")
    print(sqlv["kpi_gate_conversion"].round(3).to_string(index=False))
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
