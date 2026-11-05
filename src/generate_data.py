"""Phase 1: synthetic source-data generator.

Run from the project root:   python -m src.generate_data

ALL DATA IS SYNTHETIC. IDs only, no names. Every effect size, noise rate and
distribution below is an ASSUMPTION (see docs/assumptions.md).
"""
import json

import numpy as np
import pandas as pd

from src.config import (
    SEED, DATA_RAW, REPORTS, DATA_START, DATA_END,
    EXPERIMENT_START, EXPERIMENT_END, set_seed,
)

# ----------------------------------------------------------------------------
# Assumptions
# ----------------------------------------------------------------------------
N_PATIENTS = 15_000
TARGET_NOSHOW = 0.22          # baseline no-show among non-cancelled appointments
EFFECT_A = 0.030              # arm A: AI voice 48h + SMS, absolute reduction
EFFECT_B = 0.015              # arm B: two-way SMS + reschedule link
CANCEL_BASE = 0.06
LATE_CANCEL_BASE = 0.05
ARM_B_EXTRA_CANCEL = 0.02     # guardrail: reschedule link raises cancellations
ARM_B_EXTRA_LATE_CANCEL = 0.015
APPT_RATE_K = 15.0            # tunes total appointment volume (~120k)

DIRT = {
    "dup_rate": 0.01,
    "missing_payer_rate": 0.02,
    "payer_variant_rate": 0.10,
    "tz_utc_rate": 0.15,
    "orphan_rate": 0.003,
    "appt_before_intake_rate": 0.002,
    "amount_violation_rate": 0.002,
    "missing_score_rate": 0.03,
}

AGE_BANDS = ["18-24", "25-34", "35-49", "50-64", "65+"]
AGE_P = [0.18, 0.27, 0.28, 0.19, 0.08]
AGE_EFF = {"18-24": 0.25, "25-34": 0.10, "35-49": 0.0, "50-64": -0.10, "65+": -0.15}
PAYERS = ["Medicaid", "Medicare", "Commercial", "Self-pay"]
PAYER_P = [0.38, 0.12, 0.38, 0.12]
PAYER_EFF = {"Medicaid": 0.35, "Medicare": -0.10, "Commercial": -0.25, "Self-pay": 0.20}
PTYPE_EFF = {"psychiatrist": -0.10, "NP": 0.0, "therapist": 0.12}
DOW_EFF = np.array([0.15, 0.0, 0.0, 0.05, 0.20])   # Mon..Fri
PAYER_VARIANTS = {
    "Medicaid": ["medicaid", "MEDICAID", "Medicaid ", "MCAID"],
    "Medicare": ["medicare", "MEDICARE", "Medicare ", "MCARE"],
    "Commercial": ["commercial", "COMMERCIAL", "Comm", "Commercial "],
    "Self-pay": ["self-pay", "Self Pay", "SELF_PAY", "selfpay"],
}

END = pd.Timestamp(DATA_END)
EXP_START = pd.Timestamp(EXPERIMENT_START)
EXP_END = pd.Timestamp(EXPERIMENT_END)
TS_FMT = "%Y-%m-%d %H:%M:%S"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def calibrate_intercept(z, target):
    """Bisection: find b so that mean(sigmoid(z + b)) == target."""
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if sigmoid(z + mid).mean() > target:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def add(ts, amount, unit):
    """Datetimes (Series/Index) + numeric array of timedeltas -> DatetimeIndex."""
    return pd.DatetimeIndex(ts) + pd.to_timedelta(np.asarray(amount), unit=unit)


def noshow_rate(df):
    d = df[df["status"] != "cancelled"]
    return float((d["status"] == "no_show").mean()) if len(d) else float("nan")


# ----------------------------------------------------------------------------
# Clean tables
# ----------------------------------------------------------------------------
def make_clinics():
    spec = [
        ("Buffalo", "NY", "America/New_York"), ("Rochester", "NY", "America/New_York"),
        ("Albany", "NY", "America/New_York"), ("Syracuse", "NY", "America/New_York"),
        ("Cleveland", "OH", "America/New_York"), ("Chicago", "IL", "America/Chicago"),
        ("Minneapolis", "MN", "America/Chicago"), ("Dallas", "TX", "America/Chicago"),
        ("Denver", "CO", "America/Denver"), ("Phoenix", "AZ", "America/Phoenix"),
        ("Seattle", "WA", "America/Los_Angeles"), ("Sacramento", "CA", "America/Los_Angeles"),
    ]
    df = pd.DataFrame(spec, columns=["city", "state", "timezone"])
    df.insert(0, "clinic_id", [f"C{i + 1:02d}" for i in range(len(df))])
    return df


def make_providers(rng, clinics):
    types = np.array(["psychiatrist"] * 12 + ["NP"] * 18 + ["therapist"] * 30)
    rng.shuffle(types)
    n = len(types)
    df = pd.DataFrame({
        "provider_id": [f"PR{i + 1:03d}" for i in range(n)],
        "clinic_id": [clinics["clinic_id"].iloc[i % len(clinics)] for i in range(n)],
        "provider_type": types,
    })
    cap = {"psychiatrist": 30, "NP": 28, "therapist": 25}   # ASSUMPTION: slots/week
    df["weekly_slot_capacity"] = df["provider_type"].map(cap)
    return df


def make_patients(rng, clinics):
    n = N_PATIENTS
    w = rng.dirichlet(np.ones(len(clinics)) * 8)
    start = pd.Timestamp(DATA_START)
    span = (pd.Timestamp("2026-03-31") - start).days
    created = start + pd.to_timedelta(rng.integers(0, span + 1, size=n), unit="D")
    u = rng.normal(size=n)                                  # latent frailty (hidden)
    df = pd.DataFrame({
        "patient_id": [f"P{i + 1:06d}" for i in range(n)],
        "clinic_id": rng.choice(clinics["clinic_id"].to_numpy(), size=n, p=w),
        "created_date": created,
        "age_band": rng.choice(AGE_BANDS, size=n, p=AGE_P),
        "payer_type": rng.choice(PAYERS, size=n, p=PAYER_P),
        "language": rng.choice(["English", "Spanish", "Other"], size=n, p=[0.80, 0.13, 0.07]),
        "prior_no_show_count": np.minimum(rng.poisson(np.exp(-0.6 + 0.6 * u)), 8),
        "_frailty": u,
        "_tele_prop": rng.beta(2.0, 2.4, size=n),
        "_arm": rng.choice(["control", "arm_a", "arm_b"], size=n),  # patient-level randomization
    })
    return df


def make_intake(rng, pat):
    n = len(pat)
    u = pat["_frailty"].to_numpy()
    medicaid = (pat["payer_type"] == "Medicaid").to_numpy()
    phq = np.clip(np.rint(9 + 2.0 * u + rng.normal(0, 4.5, n)), 0, 27).astype(int)
    gad = np.clip(np.rint(7 + 0.4 * (phq - 9) + 1.0 * u + rng.normal(0, 3.2, n)), 0, 21).astype(int)
    acuity = np.where((phq >= 20) | (gad >= 15), "high",
                      np.where((phq >= 10) | (gad >= 10), "moderate", "low"))
    mins = rng.integers(8, 17, n) * 60 + rng.integers(0, 60, n)
    df = pd.DataFrame({
        "patient_id": pat["patient_id"].to_numpy(),
        "intake_ts": add(pat["created_date"], mins, "m"),
        "phq9_total": phq,
        "gad7_total": gad,
        "acuity": acuity,
        "sdoh_housing": (rng.random(n) < 0.08 + 0.08 * medicaid).astype(int),
        "sdoh_transport": (rng.random(n) < 0.12 + 0.10 * medicaid).astype(int),
        "sdoh_food": (rng.random(n) < 0.10 + 0.08 * medicaid).astype(int),
        "sdoh_employment": (rng.random(n) < 0.18 + 0.08 * medicaid).astype(int),
    })
    df.insert(0, "intake_id", [f"I{i + 1:06d}" for i in range(n)])
    return df


def make_eligibility(rng, pat, intake):
    n = len(pat)
    payer = pat["payer_type"].to_numpy()
    medicaid = payer == "Medicaid"
    r = rng.random(n)
    p_inactive = 0.04 + 0.04 * medicaid
    first = np.where(r < p_inactive, "inactive",
                     np.where(r < p_inactive + 0.04, "pending_info", "active"))
    first = np.where(payer == "Self-pay", "not_applicable", first)

    t1 = add(intake["intake_ts"], rng.integers(1, 49, n), "h")
    rev = (first == "active") & (rng.random(n) < 0.06)                      # routine re-verification
    retry = np.isin(first, ["inactive", "pending_info"]) & (rng.random(n) < 0.60)
    second = np.where(retry, np.where(rng.random(n) < 0.55, "active", "inactive"), "active")
    has2 = rev | retry
    final = np.where(has2, second, first)
    blocked = np.isin(final, ["inactive", "pending_info"])

    t2 = add(t1, rng.integers(24, 97, n), "h")
    pid = pat["patient_id"].to_numpy()
    e1 = pd.DataFrame({"patient_id": pid, "checked_ts": t1,
                       "payer_type_checked": payer, "eligibility_status": first})
    e2 = pd.DataFrame({"patient_id": pid[has2], "checked_ts": t2[has2],
                       "payer_type_checked": payer[has2], "eligibility_status": second[has2]})
    df = pd.concat([e1, e2]).sort_values("checked_ts", kind="stable").reset_index(drop=True)
    df.insert(0, "eligibility_id", [f"E{i + 1:06d}" for i in range(len(df))])
    return df, blocked


def make_prior_auth(rng, pat, intake):
    n = len(pat)
    payer = pat["payer_type"].to_numpy()
    p_req = pd.Series(payer).map({"Medicaid": 0.40, "Medicare": 0.20,
                                  "Commercial": 0.45, "Self-pay": 0.0}).to_numpy()
    req = rng.random(n) < p_req
    idx = np.where(req)[0]
    m = len(idx)
    pay = payer[idx]
    acu = intake["acuity"].to_numpy()[idx]
    urgent = rng.random(m) < np.where(acu == "high", 0.75, 0.10)
    submitted = add(intake["intake_ts"].iloc[idx], rng.integers(4, 97, m), "h")
    median_h = np.where(urgent, 40.0, 96.0) * np.where(pay == "Medicaid", 1.2, 1.0)
    turn_h = rng.lognormal(np.log(median_h), np.where(urgent, 0.55, 0.60))
    decided = submitted + pd.to_timedelta(turn_h, unit="h")
    denied = rng.random(m) < (0.12 + 0.05 * (pay == "Medicaid"))
    reasons = rng.choice(["missing_documentation", "not_medically_necessary",
                          "out_of_network", "incomplete_form"], size=m, p=[0.35, 0.30, 0.15, 0.20])
    pending = np.asarray(decided > END + pd.Timedelta(days=1))
    status = np.where(pending, "pending", np.where(denied, "denied", "approved"))

    df = pd.DataFrame({
        "patient_id": pat["patient_id"].to_numpy()[idx],
        "submitted_ts": submitted,
        "decided_ts": decided.where(~pending),
        "urgency": np.where(urgent, "urgent", "standard"),
        "status": status,
        "denial_reason": np.where(denied & ~pending, reasons, None),
    }).sort_values("submitted_ts", kind="stable").reset_index(drop=True)
    df.insert(0, "pa_id", [f"PA{i + 1:06d}" for i in range(len(df))])

    pa_denied = np.zeros(n, dtype=bool)
    pa_denied[idx[status == "denied"]] = True
    return df, req, pa_denied


def make_appointments(rng, pat, intake, elig_blocked, pa_req, pa_denied, providers):
    n = len(pat)
    payer = pat["payer_type"].to_numpy()
    medicaid = payer == "Medicaid"
    transport = intake["sdoh_transport"].to_numpy()
    housing = intake["sdoh_housing"].to_numpy()

    # ---- funnel drop-off: some patients never get an appointment
    p_drop = (0.05 + 0.10 * elig_blocked + 0.25 * pa_denied + 0.04 * medicaid
              + 0.05 * transport + 0.02 * housing)
    dropped = rng.random(n) < p_drop

    # ---- appointment dates
    created = pd.DatetimeIndex(pat["created_date"])
    first_off = np.floor(3 + rng.gamma(2.0, 5.0, n) + 5 * pa_req + 3 * medicaid).astype(int)
    first_date = created + pd.to_timedelta(first_off, unit="D")
    remaining = np.asarray((END - first_date).days)
    lam = APPT_RATE_K * np.clip(remaining, 0, None) / 546.0
    n_app = 1 + rng.poisson(lam)
    n_app = np.where(dropped | (remaining < 0), 0, n_app)

    pidx = np.repeat(np.arange(n), n_app)
    total = pidx.size
    rank = np.arange(total) - np.repeat(np.cumsum(n_app) - n_app, n_app)
    rem_row = remaining[pidx]
    offset = np.where(rank == 0, 0, np.floor(rng.random(total) * (rem_row + 1))).astype(int)
    appt_date = first_date[pidx] + pd.to_timedelta(offset, unit="D")
    dow = np.asarray(appt_date.dayofweek)
    appt_date = appt_date + pd.to_timedelta(np.where(dow == 5, 2, np.where(dow == 6, 1, 0)), unit="D")
    keep = np.asarray(appt_date <= END)
    pidx, appt_date = pidx[keep], appt_date[keep]
    m = pidx.size

    hour = rng.choice([9, 10, 11, 13, 14, 15, 16, 17], size=m,
                      p=[0.14, 0.15, 0.13, 0.10, 0.13, 0.13, 0.12, 0.10])
    minute = rng.choice([0, 30], size=m)
    appt_ts = appt_date + pd.to_timedelta(hour * 60 + minute, unit="m")
    dow = np.asarray(appt_date.dayofweek)                   # 0..4 after the weekend shift

    # ---- lead time (scheduling always after intake)
    gap = np.asarray((appt_date - created[pidx]).days)      # >= 3
    lead = np.minimum(np.clip(np.rint(rng.gamma(1.8, 7.0, m)), 0, 60).astype(int), gap - 1)
    sched_ts = appt_ts - pd.to_timedelta(lead, unit="D") - pd.to_timedelta(rng.integers(15, 61, m), unit="m")

    # ---- providers (same clinic as the patient; 85% see their primary provider)
    pat_clinic = pat["clinic_id"].to_numpy()
    prov_clinic = providers["clinic_id"].to_numpy()
    by_clinic = {c: np.where(prov_clinic == c)[0] for c in providers["clinic_id"].unique()}
    primary = np.zeros(n, dtype=int)
    for c, arr in by_clinic.items():
        mk = pat_clinic == c
        primary[mk] = rng.choice(arr, size=int(mk.sum()))
    prov_idx = primary[pidx]
    clinic_row = pat_clinic[pidx]
    switch = rng.random(m) < 0.15
    for c, arr in by_clinic.items():
        mk = switch & (clinic_row == c)
        prov_idx[mk] = rng.choice(arr, size=int(mk.sum()))
    ptype = providers["provider_type"].to_numpy()[prov_idx]

    modality = np.where(rng.random(m) < pat["_tele_prop"].to_numpy()[pidx], "telehealth", "in_person")

    # ---- planted no-show structure (logit scale)
    payer_r = payer[pidx]
    age_r = pat["age_band"].to_numpy()[pidx]
    prior_r = pat["prior_no_show_count"].to_numpy()[pidx]
    phq_r = intake["phq9_total"].to_numpy()[pidx]
    u_r = pat["_frailty"].to_numpy()[pidx]
    inter = ((lead > 21) & (payer_r == "Medicaid") & (modality == "in_person")).astype(float)

    z = (0.03 * np.minimum(lead, 40)                         # lead time, saturating
         - 0.40 * (lead <= 1)                                # same/next-day bookings show up
         + pd.Series(payer_r).map(PAYER_EFF).to_numpy(dtype=float)
         + 0.30 * (modality == "in_person")
         + 0.18 * np.minimum(prior_r, 6)
         + pd.Series(age_r).map(AGE_EFF).to_numpy(dtype=float)
         + 0.015 * (phq_r - 10)
         + DOW_EFF[dow]
         + np.where(hour <= 9, 0.20, np.where(hour >= 16, 0.10, 0.0))
         + pd.Series(ptype).map(PTYPE_EFF).to_numpy(dtype=float)
         + 0.50 * u_r                                        # unobserved patient trait
         + 0.90 * inter)                                     # NON-LINEAR: long lead x Medicaid x in-person
    b = calibrate_intercept(z, TARGET_NOSHOW)
    p0 = sigmoid(z + b)

    # ---- reminder experiment (patient-level arm, only inside the window)
    in_window = np.asarray((appt_date >= EXP_START) & (appt_date <= EXP_END))
    arm_row = np.where(in_window, pat["_arm"].to_numpy()[pidx], "standard")
    mult = 1 + 0.6 * (payer_r == "Medicaid") + 0.5 * (lead >= 14)   # stronger for Medicaid / long lead
    effect = np.zeros(m)
    for arm, target in (("arm_a", EFFECT_A), ("arm_b", EFFECT_B)):
        mk = arm_row == arm
        effect[mk] = target * mult[mk] / mult[mk].mean()           # mean effect == planted effect
    p_final = np.clip(p0 - effect, 0.01, 0.99)

    p_cancel = CANCEL_BASE + 0.0015 * lead + ARM_B_EXTRA_CANCEL * (arm_row == "arm_b")
    p_late = LATE_CANCEL_BASE + ARM_B_EXTRA_LATE_CANCEL * (arm_row == "arm_b")
    u_c, u_n, u_l = rng.random(m), rng.random(m), rng.random(m)
    status = np.where(u_c < p_cancel, "cancelled",
                      np.where(u_n < p_final, "no_show",
                               np.where(u_l < p_late, "late_cancel", "completed")))

    df = pd.DataFrame({
        "patient_id": pat["patient_id"].to_numpy()[pidx],
        "provider_id": providers["provider_id"].to_numpy()[prov_idx],
        "clinic_id": clinic_row,
        "scheduled_ts": sched_ts,
        "appt_ts": appt_ts,
        "lead_days": lead,
        "modality": modality,
        "status": status,
        "reminder_arm": arm_row,
        "_p0": p0,
        "_effect": effect,
    }).sort_values("appt_ts", kind="stable").reset_index(drop=True)
    df.insert(0, "appointment_id", [f"A{i + 1:07d}" for i in range(len(df))])
    return df, b


def make_claims(rng, appts, pat, providers, pa_denied):
    done = appts[appts["status"] == "completed"].reset_index(drop=True)
    pmap = pat.set_index("patient_id")["payer_type"]
    payer = pmap.reindex(done["patient_id"]).to_numpy()
    ptype = providers.set_index("provider_id")["provider_type"].reindex(done["provider_id"]).to_numpy()
    pa_flag = pd.Series(pa_denied, index=pat["patient_id"]).reindex(done["patient_id"]).to_numpy(dtype=bool)
    m = len(done)

    base = pd.Series(ptype).map({"psychiatrist": 260.0, "NP": 190.0, "therapist": 150.0}).to_numpy(dtype=float)
    billed = np.round(base * rng.lognormal(0, 0.12, m), 2)
    ratio = pd.Series(payer).map({"Medicaid": 0.52, "Medicare": 0.68,
                                  "Commercial": 0.80, "Self-pay": 0.60}).to_numpy(dtype=float)
    allowed = np.round(np.minimum(billed * ratio * rng.uniform(0.95, 1.05, m), billed), 2)

    p_den = pd.Series(payer).map({"Medicaid": 0.11, "Medicare": 0.07,
                                  "Commercial": 0.08, "Self-pay": 0.04}).to_numpy(dtype=float) + 0.20 * pa_flag
    denied0 = rng.random(m) < np.clip(p_den, 0, 0.9)
    code_rand = rng.choice(["CO-16", "CO-50", "CO-27", "CO-29", "CO-4", "CO-18"],
                           size=m, p=[0.30, 0.20, 0.15, 0.12, 0.15, 0.08])
    code = np.where(pa_flag & (rng.random(m) < 0.70), "CO-197", code_rand)  # no prior auth on file
    code = np.where(denied0, code, None)

    submit = pd.DatetimeIndex(done["appt_ts"]).normalize() + pd.to_timedelta(rng.integers(1, 8, m), unit="D")
    recovered = denied0 & (rng.random(m) < 0.40)
    median_days = pd.Series(payer).map({"Medicaid": 38, "Medicare": 22,
                                        "Commercial": 26, "Self-pay": 45}).to_numpy(dtype=float)
    days = np.rint(rng.lognormal(np.log(median_days), 0.45)) + 30 * recovered
    paid_date = submit + pd.to_timedelta(days, unit="D")
    past_end = np.asarray(paid_date > END)
    status = np.where(denied0 & ~recovered, "denied", np.where(past_end, "pending", "paid"))
    frac = np.where(payer == "Commercial", rng.uniform(0, 0.20, m), rng.uniform(0, 0.05, m))
    paid_amt = np.where(status == "paid", np.round(allowed * (1 - frac), 2), 0.0)

    df = pd.DataFrame({
        "appointment_id": done["appointment_id"].to_numpy(),
        "patient_id": done["patient_id"].to_numpy(),
        "billed_amount": billed,
        "allowed_amount": allowed,
        "paid_amount": paid_amt,
        "claim_status": status,
        "denial_code": code,                       # first-submission denial code (kept if later recovered)
        "resubmission_count": recovered.astype(int),
        "submit_date": submit,
        "paid_date": paid_date.where(status == "paid"),
    })
    df = df[np.asarray(submit <= END)]             # claims not yet submitted are not in the table
    df = df.sort_values("submit_date", kind="stable").reset_index(drop=True)
    df.insert(0, "claim_id", [f"CL{i + 1:07d}" for i in range(len(df))])
    return df


def make_assignments(pat, appts):
    enrolled = appts.loc[appts["reminder_arm"] != "standard", "patient_id"].unique()
    a = pat[pat["patient_id"].isin(enrolled)][["patient_id", "_arm", "created_date"]].copy()
    a["assigned_date"] = a["created_date"].clip(lower=EXP_START)
    a = a.rename(columns={"_arm": "arm"}).drop(columns="created_date").reset_index(drop=True)
    a.insert(0, "assignment_id", [f"X{i + 1:06d}" for i in range(len(a))])
    return a


# ----------------------------------------------------------------------------
# Dirt injection (raw copies only; clean tables stay in memory as ground truth)
# ----------------------------------------------------------------------------
def make_dirty(rng, clinics, providers, pat, intake, elig, pa, appts, claims, assign):
    log = {}

    def seed():
        return int(rng.integers(0, 2**31 - 1))

    def add_dups(df, key):
        d = df.sample(frac=DIRT["dup_rate"], random_state=seed())
        out = pd.concat([df, d]).sort_values(key, kind="stable").reset_index(drop=True)
        return out, int(len(d))

    def drop_private(df):
        return df.drop(columns=[c for c in df.columns if c.startswith("_")]).copy()

    def orphan_ids(n, prefix, width):
        return [f"{prefix}{x:0{width}d}" for x in rng.integers(0, 10**width, n)]

    # patients: payer variants + missing payer + duplicates
    p = drop_private(pat)
    pay = p["payer_type"].astype(object)
    var_mask = rng.random(len(p)) < DIRT["payer_variant_rate"]
    for canon, opts in PAYER_VARIANTS.items():
        mk = var_mask & (p["payer_type"] == canon).to_numpy()
        if mk.any():
            pay.loc[mk] = rng.choice(opts, size=int(mk.sum()))
    miss = rng.random(len(p)) < DIRT["missing_payer_rate"]
    pay.loc[miss] = np.nan
    p["payer_type"] = pay
    p["created_date"] = p["created_date"].dt.strftime("%Y-%m-%d")
    log["patients_payer_missing"] = int(miss.sum())
    log["patients_payer_variants"] = int((var_mask & ~miss).sum())
    p, log["patients_duplicate_rows"] = add_dups(p, "patient_id")

    # intake: missing PHQ-9 / GAD-7
    i = drop_private(intake)
    for col in ("phq9_total", "gad7_total"):
        mk = rng.random(len(i)) < DIRT["missing_score_rate"]
        i[col] = i[col].astype("Int64")
        i.loc[mk, col] = pd.NA
        log[f"intake_{col}_missing"] = int(mk.sum())
    i["intake_ts"] = i["intake_ts"].dt.strftime(TS_FMT)

    # eligibility: duplicates
    e = elig.copy()
    e["checked_ts"] = e["checked_ts"].dt.strftime(TS_FMT)
    e, log["eligibility_duplicate_rows"] = add_dups(e, "eligibility_id")

    # prior auth: orphan patient ids
    pr = pa.copy()
    mk = rng.random(len(pr)) < DIRT["orphan_rate"]
    pr.loc[mk, "patient_id"] = orphan_ids(int(mk.sum()), "P9", 5)
    log["prior_auth_orphan_patient_id"] = int(mk.sum())
    pr["submitted_ts"] = pr["submitted_ts"].dt.strftime(TS_FMT)
    pr["decided_ts"] = pr["decided_ts"].dt.strftime(TS_FMT)

    # appointments: pre-intake rows, mixed timezone formats, orphans, duplicates
    a = drop_private(appts)
    created = pat.set_index("patient_id")["created_date"].reindex(a["patient_id"]).to_numpy()
    bi = np.where(rng.random(len(a)) < DIRT["appt_before_intake_rate"])[0]
    new_appt = (pd.DatetimeIndex(created[bi]) - pd.to_timedelta(rng.integers(1, 31, len(bi)), unit="D")
                + pd.Timedelta(hours=10))
    a.loc[bi, "appt_ts"] = new_appt
    a.loc[bi, "scheduled_ts"] = new_appt - pd.Timedelta(days=2)
    a.loc[bi, "lead_days"] = 2
    log["appointments_before_patient_exists"] = int(len(bi))

    use_utc = rng.random(len(a)) < DIRT["tz_utc_rate"]
    sched_s = a["scheduled_ts"].dt.strftime(TS_FMT)
    appt_s = a["appt_ts"].dt.strftime(TS_FMT)
    tz_of = a["clinic_id"].map(clinics.set_index("clinic_id")["timezone"])
    for tz, grp in a.groupby(tz_of):
        idx = grp.index[use_utc[grp.index]]
        if len(idx) == 0:
            continue
        for col, out in (("scheduled_ts", sched_s), ("appt_ts", appt_s)):
            utc = a.loc[idx, col].dt.tz_localize(tz).dt.tz_convert("UTC")
            out.loc[idx] = utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    a["scheduled_ts"], a["appt_ts"] = sched_s, appt_s
    log["appointments_utc_timestamp_rows"] = int(use_utc.sum())

    mk = rng.random(len(a)) < DIRT["orphan_rate"]
    a.loc[mk, "patient_id"] = orphan_ids(int(mk.sum()), "P9", 5)
    log["appointments_orphan_patient_id"] = int(mk.sum())
    mk = rng.random(len(a)) < 0.002
    a.loc[mk, "provider_id"] = "PR999"
    log["appointments_orphan_provider_id"] = int(mk.sum())
    a, log["appointments_duplicate_rows"] = add_dups(a, "appointment_id")

    # claims: amount-rule violations, orphan appointment ids, duplicates
    c = claims.copy()
    k = rng.random(len(c)) < DIRT["amount_violation_rate"]
    half = rng.random(len(c)) < 0.5
    v1, v2 = k & half, k & ~half
    c.loc[v1, "paid_amount"] = np.round(c.loc[v1, "allowed_amount"] * 1.25, 2)    # paid > allowed
    c.loc[v2, "allowed_amount"] = np.round(c.loc[v2, "billed_amount"] * 1.20, 2)  # allowed > billed
    log["claims_paid_gt_allowed"] = int(v1.sum())
    log["claims_allowed_gt_billed"] = int(v2.sum())
    mk = rng.random(len(c)) < DIRT["orphan_rate"]
    c.loc[mk, "appointment_id"] = orphan_ids(int(mk.sum()), "A9", 6)
    log["claims_orphan_appointment_id"] = int(mk.sum())
    c["submit_date"] = c["submit_date"].dt.strftime("%Y-%m-%d")
    c["paid_date"] = c["paid_date"].dt.strftime("%Y-%m-%d")
    c, log["claims_duplicate_rows"] = add_dups(c, "claim_id")

    asg = assign.copy()
    asg["assigned_date"] = asg["assigned_date"].dt.strftime("%Y-%m-%d")

    raw = {"clinics": clinics, "providers": providers, "patients": p, "intake": i,
           "eligibility_checks": e, "prior_authorizations": pr, "appointments": a,
           "claims": c, "experiment_assignments": asg}
    return raw, log


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    rng = set_seed()
    clinics = make_clinics()
    providers = make_providers(rng, clinics)
    pat = make_patients(rng, clinics)
    intake = make_intake(rng, pat)
    elig, elig_blocked = make_eligibility(rng, pat, intake)
    pa, pa_req, pa_denied = make_prior_auth(rng, pat, intake)
    appts, intercept = make_appointments(rng, pat, intake, elig_blocked, pa_req, pa_denied, providers)
    claims = make_claims(rng, appts, pat, providers, pa_denied)
    assign = make_assignments(pat, appts)

    # ---- sanity summary on the CLEAN data (before dirt)
    payer_row = appts["patient_id"].map(pat.set_index("patient_id")["payer_type"])
    cell = (payer_row == "Medicaid") & (appts["modality"] == "in_person") & (appts["lead_days"] > 21)
    print("\n=== CLEAN-DATA SANITY (synthetic) ===")
    print(f"patients with >=1 appointment: {appts['patient_id'].nunique():,} of {len(pat):,}")
    print(f"overall no-show rate (non-cancelled): {noshow_rate(appts):.4f}")
    print(f"  Medicaid x in-person x lead>21d: {noshow_rate(appts[cell]):.4f}  (n={int(cell.sum()):,})")
    print(f"  everyone else:                   {noshow_rate(appts[~cell]):.4f}")
    print("in-window no-show rate by arm (observed, includes noise):")
    for arm in ["standard", "control", "arm_a", "arm_b"]:
        d = appts[appts["reminder_arm"] == arm]
        print(f"  {arm:9s} n={len(d):>7,}  no-show={noshow_rate(d):.4f}")

    raw, dirt_log = make_dirty(rng, clinics, providers, pat, intake, elig, pa, appts, claims, assign)

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    print("\n=== RAW FILES WRITTEN (dirty) ===")
    counts = {}
    for name, df in raw.items():
        df.to_csv(DATA_RAW / f"{name}.csv", index=False)
        counts[name] = int(len(df))
        print(f"  {name:24s} {len(df):>9,} rows")

    realized = {arm: float(appts.loc[appts["reminder_arm"] == arm, "_effect"].mean() * 100)
                for arm in ("arm_a", "arm_b")}
    manifest = {
        "seed": SEED,
        "synthetic": True,
        "raw_row_counts": counts,
        "clean_row_counts": {"patients": len(pat), "appointments": len(appts), "claims": len(claims)},
        "calibrated_logit_intercept": float(intercept),
        "mean_p0_baseline_noshow": float(appts["_p0"].mean()),
        "planted_effect_pp": {"arm_a": EFFECT_A * 100, "arm_b": EFFECT_B * 100},
        "realized_mean_effect_pp_on_probability": realized,
        "dirt_injected": dirt_log,
        "dirt_rates_assumed": DIRT,
    }
    with open(REPORTS / "generation_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print("\n=== DIRT INJECTED ===")
    for k, v in dirt_log.items():
        print(f"  {k:38s} {v:>6,}")
    print(f"\nmanifest -> {REPORTS / 'generation_manifest.json'}")


if __name__ == "__main__":
    main()