"""Known-answer tests for the pandas KPI helpers in src/kpis.py (hand-computed expectations)."""
import numpy as np
import pandas as pd
import pytest

from src import kpis


def test_no_show_rate_known_answer():
    # Jan: 4 resolved (2 completed, 1 no_show, 1 late_cancel) + 1 cancelled (excluded) -> 1/4 and 1/4
    fa = pd.DataFrame({
        "appt_date": pd.to_datetime(["2025-01-05"] * 5 + ["2025-02-05"] * 2),
        "status": ["completed", "completed", "no_show", "late_cancel", "cancelled", "no_show", "completed"],
    })
    out = kpis.pd_appointments(fa).set_index("year_month")
    assert out.loc["2025-01", "resolved"] == 4
    assert out.loc["2025-01", "no_show_rate"] == pytest.approx(0.25)
    assert out.loc["2025-01", "late_cancel_rate"] == pytest.approx(0.25)
    assert out.loc["2025-02", "no_show_rate"] == pytest.approx(0.5)


def test_claims_clean_rate_known_answer():
    fc = pd.DataFrame({
        "submit_date": pd.to_datetime(["2025-03-01"] * 4),
        "denial_code": [None, None, "CO-16", "CO-50"],
        "claim_status": ["paid", "paid", "denied", "paid"],
        "billed_amount": [100, 100, 100, 100],
        "allowed_amount": [80, 80, 80, 80],
        "paid_amount": [80, 80, 0, 80],
    })
    out = kpis.pd_claims(fc).iloc[0]
    assert out["clean_claim_rate"] == pytest.approx(0.5)
    assert out["first_pass_denial_rate"] == pytest.approx(0.5)
    assert out["final_denial_rate"] == pytest.approx(0.25)   # only 1 of 4 ended denied
    assert out["allowed_total"] == pytest.approx(320)


def test_days_in_ar_grouped_by_paid_month():
    fc = pd.DataFrame({
        "claim_status": ["paid", "paid", "denied"],
        "paid_date": pd.to_datetime(["2025-03-11", "2025-03-21", None]),
        "submit_date": pd.to_datetime(["2025-03-01", "2025-03-01", "2025-03-01"]),
    })
    out = kpis.pd_ar(fc).iloc[0]
    assert out["year_month"] == "2025-03"
    assert out["paid_claims"] == 2
    assert out["mean_days_in_ar"] == pytest.approx(15.0)     # (10 + 20) / 2
    assert out["median_days_in_ar"] == pytest.approx(15.0)


def test_leakage_only_mature_months():
    fc = pd.DataFrame({
        "claim_id": ["a", "b", "c", "d"],
        "submit_date": pd.to_datetime(["2026-02-01", "2026-02-02", "2026-02-03", "2026-05-01"]),
        "claim_status": ["paid", "denied", "pending", "pending"],
        "allowed_amount": [100, 100, 100, 100],
    })
    out = kpis.pd_leakage(fc, "2026-03")
    assert list(out["year_month"]) == ["2026-02"]            # May excluded (not yet 90 days old)
    assert out.iloc[0]["leakage_rate"] == pytest.approx(2 / 3)   # (100 + 100) / 300


def test_prior_auth_sla_breach_thresholds():
    t0 = pd.Timestamp("2025-04-01 08:00")
    fpa = pd.DataFrame({
        "submitted_ts": [t0] * 4,
        "decided_ts": [t0 + pd.Timedelta(hours=71), t0 + pd.Timedelta(hours=73),   # urgent: ok, breach
                       t0 + pd.Timedelta(hours=167), t0 + pd.Timedelta(hours=169)],  # standard: ok, breach
        "urgency": ["urgent", "urgent", "standard", "standard"],
        "status": ["approved", "approved", "approved", "denied"],
    })
    out = kpis.pd_pa(fpa).set_index("urgency")
    assert out.loc["urgent", "sla_breach_rate"] == pytest.approx(0.5)
    assert out.loc["standard", "sla_breach_rate"] == pytest.approx(0.5)
    assert out.loc["standard", "denial_rate"] == pytest.approx(0.5)


def test_pending_prior_auth_excluded_from_rates():
    t0 = pd.Timestamp("2025-04-01 08:00")
    fpa = pd.DataFrame({
        "submitted_ts": [t0, t0],
        "decided_ts": [t0 + pd.Timedelta(hours=10), pd.NaT],
        "urgency": ["urgent", "urgent"],
        "status": ["approved", "pending"],
    })
    out = kpis.pd_pa(fpa).iloc[0]
    assert out["requests"] == 2 and out["decided"] == 1
    assert out["sla_breach_rate"] == pytest.approx(0.0)


def test_funnel_is_nested_and_percentages_correct():
    dp = pd.DataFrame({"patient_id": list("ABCD")})
    fa = pd.DataFrame({"patient_id": list("ABC"), "status": ["completed", "completed", "no_show"]})
    fc = pd.DataFrame({"patient_id": ["A", "B"], "claim_status": ["paid", "denied"]})
    out = kpis.pd_funnel(dp, fa, fc)
    assert list(out["patients"]) == [4, 3, 2, 2, 1]
    assert out["pct_of_intake"].iloc[-1] == pytest.approx(0.25)
    assert out["pct_of_prev_stage"].iloc[1] == pytest.approx(0.75)
