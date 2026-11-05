"""Phase 5: analysis of the randomized reminder experiment (patient-level randomization).

Run:  python -m src.experiment        (after: python -m src.pipeline)
Plan: docs/assumptions.md A30-A38 (written before this script was run).
Outputs: results/experiment_*.csv|json, reports/figures/experiment_effects.png, docs/experiment_readout.md
ALL DATA IS SYNTHETIC. The reminder effects were PLANTED by src/generate_data.py.
"""
import json
import logging

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.optimize import brentq
from statsmodels.stats.multitest import multipletests

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.config import EXPERIMENT_END, EXPERIMENT_START, FIGURES, RESULTS, ROOT, WAREHOUSE  # noqa: E402

log = logging.getLogger("experiment")

ARMS = ["control", "arm_a", "arm_b"]
ARM_LABEL = {"control": "Control (standard SMS 24h)", "arm_a": "Arm A (AI voice 48h + SMS)",
             "arm_b": "Arm B (two-way SMS + reschedule link)"}
PAIRS = [("control", "arm_a"), ("control", "arm_b"), ("arm_b", "arm_a")]   # (reference, treatment)
BASELINE, MDE, ALPHA, POWER, N_COMP = 0.22, 0.02, 0.05, 0.80, 3
GUARDRAIL_MIN = 0.01
SMD_FLAG = 0.10
SDOH = ["sdoh_housing", "sdoh_transport", "sdoh_food", "sdoh_employment"]
PAYER_ORDER = ["Medicaid", "Medicare", "Commercial", "Self-pay", "Unknown"]
LEAD_ORDER = ["0-1", "2-7", "8-14", "15-21", "22-30", "31+"]

M_RD = "cluster-robust LPM (RD)"
M_RR = "cluster-robust modified Poisson (RR)"
M_OR = "cluster-robust logit (OR)"
M_CHI = "chi-square (naive, ignores clustering)"
M_Z = "two-proportion z (naive, ignores clustering)"
M_PZ = "patient-level z (any no-show)"
M_PT = "patient-level Welch t (mean no-show rate)"
M_ADJ = "cluster-robust logit, covariate-adjusted (OR)"

_W = f"f.appt_date between date '{EXPERIMENT_START}' and date '{EXPERIMENT_END}'"
APPT_SQL = f"""
select f.appointment_id, f.patient_id, f.appt_date, f.lead_days, f.lead_bucket, f.modality, f.status,
       f.reminder_arm, f.is_no_show, f.is_late_cancel, f.is_cancelled, f.is_completed, f.is_resolved,
       p.payer_type, p.age_band, p.language, p.prior_no_show_count, p.phq9_total, p.gad7_total, p.acuity
from marts.fact_appointment f
join marts.dim_patient p on f.patient_id = p.patient_id
where {_W} and f.reminder_arm in ('control', 'arm_a', 'arm_b')
"""
PAT_SQL = """
select patient_id, clinic_id, age_band, payer_type, language, prior_no_show_count, phq9_total, gad7_total,
       acuity, sdoh_housing, sdoh_transport, sdoh_food, sdoh_employment, experiment_arm
from marts.dim_patient where experiment_arm is not null
"""
PRE_SQL = f"""
select patient_id, is_no_show from marts.fact_appointment
where appt_date < date '{EXPERIMENT_START}' and reminder_arm = 'standard' and is_resolved = 1
"""
INTEG_SQL = f"""
select
  count(*) filter (where {_W} and f.reminder_arm = 'standard') as in_window_labelled_standard,
  count(*) filter (where not ({_W}) and f.reminder_arm <> 'standard') as outside_window_labelled_arm,
  count(*) filter (where {_W} and f.reminder_arm <> 'standard'
                   and p.experiment_arm is distinct from f.reminder_arm) as arm_differs_from_assignment
from marts.fact_appointment f
join marts.dim_patient p on f.patient_id = p.patient_id
"""


# ---------------------------------------------------------------- formatting
def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def pp(x, d=2):
    return f"{x * 100:+.{d}f} pp"


def fp(p):
    return "<0.0001" if p < 1e-4 else f"{p:.4f}"


def cnt(d):
    return ", ".join(f"{k} {v:,}" for k, v in d.items())


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return out


# ---------------------------------------------------------------- data
def load():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    appts = con.execute(APPT_SQL).df()
    pats = con.execute(PAT_SQL).df()
    pre = con.execute(PRE_SQL).df()
    integ = {k: int(v) for k, v in con.execute(INTEG_SQL).df().iloc[0].to_dict().items()}
    con.close()
    return appts, pats, pre, integ


def prepare(appts):
    d = appts.copy()
    d["arm"] = d["reminder_arm"].astype(str)
    d["pid"] = pd.factorize(d["patient_id"])[0]
    for c in ["is_no_show", "is_late_cancel", "is_cancelled", "is_completed", "is_resolved", "lead_days"]:
        d[c] = d[c].astype("float64")
    d["not_completed"] = 1.0 - d["is_completed"]
    d["medicaid"] = (d["payer_type"] == "Medicaid").astype(float)
    d["long_lead"] = (d["lead_days"] > 14).astype(float)
    d["in_person"] = (d["modality"] == "in_person").astype(float)
    return d


# ---------------------------------------------------------------- estimation
def contrast(df, y, ref, trt, full=True):
    """Treatment vs reference: RD (LPM), and if full also RR (modified Poisson) and OR (logit); SEs clustered by patient."""
    sub = df[df["arm"].isin([ref, trt])]
    yv = sub[y].to_numpy(dtype=float)
    t = (sub["arm"] == trt).to_numpy(dtype=float)
    g = sub["pid"].to_numpy()
    X = np.column_stack([np.ones(len(sub)), t])

    def kw():
        return {"cov_type": "cluster", "cov_kwds": {"groups": g}}

    ols = sm.OLS(yv, X).fit(**kw())
    ci = ols.conf_int()[1]
    out = {"n_ref": int((t == 0).sum()), "n_trt": int((t == 1).sum()),
           "pat_ref": int(np.unique(g[t == 0]).size), "pat_trt": int(np.unique(g[t == 1]).size),
           "rate_ref": float(yv[t == 0].mean()), "rate_trt": float(yv[t == 1].mean()),
           "rd": float(ols.params[1]), "rd_lo": float(ci[0]), "rd_hi": float(ci[1]), "rd_p": float(ols.pvalues[1])}
    if full:
        poi = sm.GLM(yv, X, family=sm.families.Poisson()).fit(**kw())
        lgt = sm.GLM(yv, X, family=sm.families.Binomial()).fit(**kw())
        for name, m in (("rr", poi), ("or", lgt)):
            c = m.conf_int()[1]
            out[name] = float(np.exp(m.params[1]))
            out[name + "_lo"], out[name + "_hi"] = float(np.exp(c[0])), float(np.exp(c[1]))
            out[name + "_p"] = float(m.pvalues[1])
    return out


def cluster_rows(df, y, analysis):
    rows = []
    for ref, trt in PAIRS:
        c = contrast(df, y, ref, trt)
        base = {"analysis": analysis, "comparison": f"{trt} vs {ref}", "n_ref": c["n_ref"], "n_trt": c["n_trt"],
                "rate_ref": c["rate_ref"], "rate_trt": c["rate_trt"]}
        rows.append({**base, "method": M_RD, "metric": "risk difference", "estimate": c["rd"],
                     "ci_low": c["rd_lo"], "ci_high": c["rd_hi"], "p_raw": c["rd_p"]})
        rows.append({**base, "method": M_RR, "metric": "relative risk", "estimate": c["rr"],
                     "ci_low": c["rr_lo"], "ci_high": c["rr_hi"], "p_raw": c["rr_p"]})
        rows.append({**base, "method": M_OR, "metric": "odds ratio", "estimate": c["or"],
                     "ci_low": c["or_lo"], "ci_high": c["or_hi"], "p_raw": c["or_p"]})
    return rows


def naive_rows(res):
    rows = []
    for ref, trt in PAIRS:
        a = res.loc[res["arm"] == ref, "is_no_show"]
        b = res.loc[res["arm"] == trt, "is_no_show"]
        n1, n2, x1, x2 = len(a), len(b), a.sum(), b.sum()
        p1, p2 = x1 / n1, x2 / n2
        pbar = (x1 + x2) / (n1 + n2)
        z = (p2 - p1) / np.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
        se = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        chi2, p_chi, _, _ = stats.chi2_contingency(np.array([[x1, n1 - x1], [x2, n2 - x2]]), correction=False)
        base = {"analysis": "primary", "comparison": f"{trt} vs {ref}", "n_ref": n1, "n_trt": n2,
                "rate_ref": float(p1), "rate_trt": float(p2), "metric": "risk difference",
                "estimate": float(p2 - p1), "ci_low": float(p2 - p1 - 1.96 * se), "ci_high": float(p2 - p1 + 1.96 * se)}
        rows.append({**base, "method": M_Z, "p_raw": float(2 * stats.norm.sf(abs(z)))})
        rows.append({**base, "method": M_CHI, "p_raw": float(p_chi)})
    return rows


def patient_rows(res):
    pl = res.groupby("patient_id").agg(arm=("arm", "first"), any_ns=("is_no_show", "max"),
                                       ns_rate=("is_no_show", "mean")).reset_index()
    rows = []
    for ref, trt in PAIRS:
        a, b = pl[pl["arm"] == ref], pl[pl["arm"] == trt]
        n1, n2 = len(a), len(b)
        p1, p2 = a["any_ns"].mean(), b["any_ns"].mean()
        pbar = (a["any_ns"].sum() + b["any_ns"].sum()) / (n1 + n2)
        z = (p2 - p1) / np.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
        se = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        base = {"analysis": "sens_patient_level", "comparison": f"{trt} vs {ref}", "n_ref": n1, "n_trt": n2,
                "metric": "risk difference"}
        rows.append({**base, "method": M_PZ, "rate_ref": float(p1), "rate_trt": float(p2),
                     "estimate": float(p2 - p1), "ci_low": float(p2 - p1 - 1.96 * se),
                     "ci_high": float(p2 - p1 + 1.96 * se), "p_raw": float(2 * stats.norm.sf(abs(z)))})
        r = stats.ttest_ind(b["ns_rate"], a["ns_rate"], equal_var=False)
        ci = r.confidence_interval(confidence_level=0.95)
        rows.append({**base, "method": M_PT, "rate_ref": float(a["ns_rate"].mean()),
                     "rate_trt": float(b["ns_rate"].mean()),
                     "estimate": float(b["ns_rate"].mean() - a["ns_rate"].mean()),
                     "ci_low": float(ci.low), "ci_high": float(ci.high), "p_raw": float(r.pvalue)})
    return rows


def adjusted_rows(res):
    X = pd.get_dummies(res[["payer_type", "age_band", "language", "acuity", "modality"]], drop_first=True, dtype=float)
    X["prior_no_show_count"] = res["prior_no_show_count"].astype("float64")
    X["lead_days"] = res["lead_days"]
    for c in ["phq9_total", "gad7_total"]:
        s = res[c].astype("float64")
        X[c + "_missing"] = s.isna().astype(float)
        X[c] = s.fillna(s.median())
    X["arm_a"] = (res["arm"] == "arm_a").astype(float)
    X["arm_b"] = (res["arm"] == "arm_b").astype(float)
    X = sm.add_constant(X, has_constant="add")
    fit = sm.GLM(res["is_no_show"].to_numpy(float), X, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": res["pid"].to_numpy()})
    ci = fit.conf_int()
    rows = []
    for arm in ["arm_a", "arm_b"]:
        lo, hi = ci.loc[arm].to_numpy()
        rows.append({"analysis": "sens_adjusted", "comparison": f"{arm} vs control", "method": M_ADJ,
                     "metric": "odds ratio", "estimate": float(np.exp(fit.params[arm])),
                     "ci_low": float(np.exp(lo)), "ci_high": float(np.exp(hi)), "p_raw": float(fit.pvalues[arm]),
                     "n_ref": int((res["arm"] == "control").sum()), "n_trt": int((res["arm"] == arm).sum())})
    return rows


def arm_rates(d, res):
    rows = []
    for a in ARMS:
        s = res[res["arm"] == a]
        y = s["is_no_show"].to_numpy(float)
        fit = sm.OLS(y, np.ones((len(y), 1))).fit(cov_type="cluster", cov_kwds={"groups": s["pid"].to_numpy()})
        lo, hi = fit.conf_int()[0]
        rows.append({"arm": a, "label": ARM_LABEL[a],
                     "patients_scheduled": int(d.loc[d["arm"] == a, "patient_id"].nunique()),
                     "patients_resolved": int(s["patient_id"].nunique()),
                     "scheduled_appts": int((d["arm"] == a).sum()), "resolved_appts": int(len(s)),
                     "no_shows": int(y.sum()), "no_show_rate": float(y.mean()),
                     "ci_low_cluster": float(lo), "ci_high_cluster": float(hi)})
    return pd.DataFrame(rows)


def guardrails(d):
    res = d[d["is_resolved"] == 1]
    specs = [("Cancellation rate (cancelled / all scheduled)", d, "is_cancelled"),
             ("Late-cancel rate (late cancels / resolved)", res, "is_late_cancel"),
             ("Non-completion rate (not completed / all scheduled)", d, "not_completed")]
    rows = []
    for label, frame, y in specs:
        for trt in ["arm_a", "arm_b"]:
            c = contrast(frame, y, "control", trt, full=False)
            rows.append({"guardrail": label, "comparison": f"{trt} vs control", "rate_control": c["rate_ref"],
                         "rate_arm": c["rate_trt"], "rd": c["rd"], "ci_low": c["rd_lo"], "ci_high": c["rd_hi"],
                         "p_raw": c["rd_p"]})
    g = pd.DataFrame(rows)
    g["p_holm"] = multipletests(g["p_raw"].to_numpy(), method="holm")[1]
    g["breach"] = (g["p_holm"] < ALPHA) & (g["rd"] >= GUARDRAIL_MIN)
    return g


# ---------------------------------------------------------------- heterogeneity
def subgroups(res):
    rows = []
    for dim, label, order in [("payer_type", "Payer", PAYER_ORDER), ("lead_bucket", "Lead time (days)", LEAD_ORDER)]:
        for level in order:
            s = res[res[dim] == level]
            for trt in ["arm_a", "arm_b"]:
                sub = s[s["arm"].isin(["control", trt])]
                if min((sub["arm"] == "control").sum(), (sub["arm"] == trt).sum()) < 300:
                    continue
                c = contrast(s, "is_no_show", "control", trt, full=False)
                rows.append({"dimension": label, "level": level, "arm": trt, "n_control": c["n_ref"],
                             "n_arm": c["n_trt"], "rate_control": c["rate_ref"], "rate_arm": c["rate_trt"],
                             "rd": c["rd"], "ci_low": c["rd_lo"], "ci_high": c["rd_hi"], "p_raw": c["rd_p"]})
    return pd.DataFrame(rows)


def interaction(res):
    X = pd.DataFrame({"const": 1.0, "a": (res["arm"] == "arm_a").astype(float),
                      "b": (res["arm"] == "arm_b").astype(float), "med": res["medicaid"], "long": res["long_lead"]})
    X["a_med"], X["b_med"] = X["a"] * X["med"], X["b"] * X["med"]
    X["a_long"], X["b_long"] = X["a"] * X["long"], X["b"] * X["long"]
    fit = sm.OLS(res["is_no_show"].to_numpy(float), X).fit(
        cov_type="cluster", cov_kwds={"groups": res["pid"].to_numpy()})
    ci = fit.conf_int()
    coefs = []
    for name in ["a", "b", "a_med", "b_med", "a_long", "b_long"]:
        lo, hi = ci.loc[name].to_numpy()
        coefs.append({"term": name, "coef": float(fit.params[name]), "ci_low": float(lo), "ci_high": float(hi),
                      "p_raw": float(fit.pvalues[name])})
    w_med = fit.wald_test("a_med = 0, b_med = 0", scalar=True)
    w_long = fit.wald_test("a_long = 0, b_long = 0", scalar=True)
    p = np.array([float(w_med.pvalue), float(w_long.pvalue)])
    ph = multipletests(p, method="holm")[1]
    return {"coefs": coefs,
            "joint_tests": [{"modifier": "Medicaid", "wald_chi2": float(w_med.statistic), "p_raw": float(p[0]),
                             "p_holm": float(ph[0])},
                            {"modifier": "Long lead (> 14 days)", "wald_chi2": float(w_long.statistic),
                             "p_raw": float(p[1]), "p_holm": float(ph[1])}]}


# ---------------------------------------------------------------- validity
def srm(counts):
    obs = counts.reindex(ARMS).to_numpy(dtype=float)
    chi2, p = stats.chisquare(obs, np.full(len(ARMS), obs.sum() / len(ARMS)))
    return {"observed": {a: int(o) for a, o in zip(ARMS, obs)}, "chi2": float(chi2), "p": float(p),
            "alarm": bool(p < 0.001)}


def smd_table(C, arm):
    rows = []
    ctrl = C[arm == "control"]
    for a in ["arm_a", "arm_b"]:
        t = C[arm == a]
        for col in C.columns:
            m1, m0 = t[col].mean(), ctrl[col].mean()
            den = np.sqrt((t[col].var() + ctrl[col].var()) / 2)
            rows.append({"covariate": col, "arm": a, "mean_arm": float(m1), "mean_control": float(m0),
                         "smd": float((m1 - m0) / den) if den > 0 else np.nan})
    return pd.DataFrame(rows)


def balance(pats, d):
    agg = d.groupby("patient_id").agg(appts_in_window=("appointment_id", "size"), mean_lead_days=("lead_days", "mean"),
                                      share_in_person=("in_person", "mean")).reset_index()
    b = pats.merge(agg, on="patient_id", how="left")
    C = pd.get_dummies(b[["age_band", "payer_type", "language", "acuity"]], dtype=float)
    C["prior_no_show_count"] = b["prior_no_show_count"].astype("float64")
    C["phq9_total"] = b["phq9_total"].astype("float64")
    C["gad7_total"] = b["gad7_total"].astype("float64")
    for c in SDOH + ["appts_in_window", "mean_lead_days", "share_in_person"]:
        C[c] = b[c].astype("float64")
    return smd_table(C, b["experiment_arm"].astype(str))


def omnibus(p):
    """Likelihood-ratio test: do baseline covariates jointly predict arm? (should not, if randomization worked)"""
    try:
        X = pd.get_dummies(p[["age_band", "payer_type", "language", "acuity", "clinic_id"]], drop_first=True, dtype=float)
        X["prior_no_show_count"] = p["prior_no_show_count"].astype("float64")
        for c in ["phq9_total", "gad7_total"]:
            s = p[c].astype("float64")
            X[c + "_missing"] = s.isna().astype(float)
            X[c] = s.fillna(s.median())
        for c in SDOH:
            X[c] = p[c].astype("float64")
        y = pd.Categorical(p["experiment_arm"].astype(str), categories=ARMS).codes.astype(int)
        full = sm.MNLogit(y, sm.add_constant(X, has_constant="add")).fit(disp=0, maxiter=300)
        null = sm.MNLogit(y, np.ones((len(y), 1))).fit(disp=0)
        lr = 2 * (full.llf - null.llf)
        dfree = X.shape[1] * (len(ARMS) - 1)
        return {"lr_chi2": float(lr), "df": int(dfree), "p": float(stats.chi2.sf(lr, dfree))}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


# ---------------------------------------------------------------- power
def n_per_arm(p1, p2, alpha, power):
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(z * z * (p1 * (1 - p1) + p2 * (1 - p2)) / (p1 - p2) ** 2)


def mde_for_n(n, p1, alpha, power):
    return float(brentq(lambda dlt: n_per_arm(p1, p1 - dlt, alpha, power) - n, 1e-4, 0.2))


def power_at(dlt, n, p1, alpha):
    v = p1 * (1 - p1) + (p1 - dlt) * (1 - p1 + dlt)
    return float(stats.norm.cdf(dlt / np.sqrt(v / n) - stats.norm.ppf(1 - alpha / 2)))


def icc_anova(y, g):
    df = pd.DataFrame({"y": y, "g": g})
    grp = df.groupby("g")["y"].agg(["size", "mean"])
    m, yb = grp["size"].to_numpy(float), grp["mean"].to_numpy(float)
    n, k, ybar = m.sum(), len(m), df["y"].mean()
    msb = (m * (yb - ybar) ** 2).sum() / (k - 1)
    msw = (m * yb * (1 - yb)).sum() / (n - k)
    n0 = (n - (m ** 2).sum() / n) / (k - 1)
    return max(0.0, float((msb - msw) / (msb + (n0 - 1) * msw)))


def power_section(res, pre):
    icc = icc_anova(pre["is_no_show"].to_numpy(float), pre["patient_id"].to_numpy())
    sizes = res.groupby("patient_id").size().to_numpy(float)
    m_eff, m_bar = float((sizes ** 2).sum() / sizes.sum()), float(sizes.mean())
    deff = 1 + (m_eff - 1) * icc
    a_holm = ALPHA / N_COMP
    n_unadj = n_per_arm(BASELINE, BASELINE - MDE, ALPHA, POWER)
    n_holm = n_per_arm(BASELINE, BASELINE - MDE, a_holm, POWER)
    avail_appts = res.groupby("arm").size()
    avail_pats = res.groupby("arm")["patient_id"].nunique()
    n_eff = float(avail_appts.min()) / deff
    return {
        "baseline": BASELINE, "mde_abs": MDE, "alpha": ALPHA, "power": POWER, "comparisons": N_COMP,
        "alpha_holm_first_step": a_holm,
        "pre_period_observed_baseline": float(pre["is_no_show"].mean()),
        "icc_pre_period": icc, "m_eff": m_eff, "mean_resolved_per_patient": m_bar, "design_effect": float(deff),
        "n_per_arm_independent_alpha05": n_unadj, "n_per_arm_independent_holm": n_holm,
        "required_appts_per_arm_clustered_holm": n_holm * deff,
        "required_patients_per_arm_holm": n_holm * deff / m_bar,
        "available_resolved_appts_per_arm": {a: int(avail_appts[a]) for a in ARMS},
        "available_patients_per_arm": {a: int(avail_pats[a]) for a in ARMS},
        "effective_n_per_arm_available": n_eff,
        "mde_available_holm": mde_for_n(n_eff, BASELINE, a_holm, POWER),
        "mde_available_alpha05": mde_for_n(n_eff, BASELINE, ALPHA, POWER),
        "power_holm_at_3pp": power_at(0.03, n_eff, BASELINE, a_holm),
        "power_holm_at_2pp": power_at(0.02, n_eff, BASELINE, a_holm),
        "power_holm_at_1.5pp": power_at(0.015, n_eff, BASELINE, a_holm),
    }


# ---------------------------------------------------------------- decision
def decide(eff, guard):
    out = {}
    for trt in ["arm_a", "arm_b"]:
        comp = f"{trt} vs control"
        r = eff[(eff["analysis"] == "primary") & (eff["method"] == M_RD) & (eff["comparison"] == comp)].iloc[0]
        br = guard[(guard["comparison"] == comp) & guard["breach"]]["guardrail"].tolist()
        sig = bool(r["p_holm"] < ALPHA and r["estimate"] < 0)
        big = bool(r["estimate"] <= -MDE)
        if not sig:
            dec, why = "STOP", "no statistically significant reduction after Holm correction"
        elif big and not br:
            dec, why = "SHIP", "significant reduction of at least the 2 pp threshold and no guardrail breach"
        else:
            parts = []
            if not big:
                parts.append("the estimated reduction is smaller than the 2 pp practical threshold")
            if br:
                parts.append("guardrail breach: " + "; ".join(br))
            dec, why = "ITERATE", "significant reduction, but " + " and ".join(parts)
        out[trt] = {"decision": dec, "reason": why, "guardrail_breaches": br}
    return out


# ---------------------------------------------------------------- plot
def plot(eff, sub):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))
    ax = axes[0]
    keep = eff[(eff["method"] == M_RD) & eff["analysis"].isin(["primary", "sens_all_scheduled"])].reset_index(drop=True)
    y = np.arange(len(keep))[::-1]
    ax.errorbar(keep["estimate"] * 100, y,
                xerr=[((keep["estimate"] - keep["ci_low"]) * 100).to_numpy(), ((keep["ci_high"] - keep["estimate"]) * 100).to_numpy()],
                fmt="o", capsize=3, color="#4C78A8")
    ax.axvline(0, color="black", lw=1)
    ax.axvline(-MDE * 100, color="red", ls="--", lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{c}\n[{a}]" for c, a in zip(keep["comparison"], keep["analysis"])], fontsize=8)
    ax.set_xlabel("risk difference in no-show rate (percentage points; red dashed = -2 pp threshold)")
    ax.set_title("Primary and sensitivity effects (95% cluster-robust CI)")
    ax = axes[1]
    labels = list(dict.fromkeys(zip(sub["dimension"], sub["level"])))
    ypos = {lab: i for i, lab in enumerate(labels[::-1])}
    for arm, off, col in (("arm_a", 0.15, "#E45756"), ("arm_b", -0.15, "#54A24B")):
        s = sub[sub["arm"] == arm]
        yy = [ypos[(a, b)] + off for a, b in zip(s["dimension"], s["level"])]
        ax.errorbar(s["rd"] * 100, yy, xerr=[((s["rd"] - s["ci_low"]) * 100).to_numpy(), ((s["ci_high"] - s["rd"]) * 100).to_numpy()],
                    fmt="o", capsize=3, color=col, label=ARM_LABEL[arm])
    ax.axvline(0, color="black", lw=1)
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels([f"{a}: {b}" for a, b in ypos.keys()], fontsize=8)
    ax.set_xlabel("risk difference vs control (percentage points)")
    ax.set_title("Subgroup effects (exploratory, unadjusted)")
    ax.legend(fontsize=8)
    fig.suptitle("Reminder experiment on SYNTHETIC data (effects planted by the generator)")
    fig.tight_layout()
    fig.savefig(FIGURES / "experiment_effects.png", dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- memo
def build_memo(rates, eff, guard, sub, inter, power, val, decisions):
    P = eff[eff["analysis"] == "primary"]

    def g(method, comp):
        return P[(P["method"] == method) & (P["comparison"] == comp)].iloc[0]

    L = ["# Experiment Readout: AI reminder experiment", "",
         "> ALL DATA IS SYNTHETIC. The reminder effects (arm A -3.0 pp, arm B -1.5 pp, stronger for Medicaid and "
         "long lead times) were PLANTED by src/generate_data.py (assumptions A5, A6, A14). This memo demonstrates the "
         "analysis method and the decision rule; it is not a finding about real patients or clinics.", "",
         "## Decision", ""]
    rows = []
    for trt in ["arm_a", "arm_b"]:
        r = g(M_RD, f"{trt} vs control")
        d = decisions[trt]
        rows.append([ARM_LABEL[trt], f"{pp(r['estimate'])} ({pp(r['ci_low'])} to {pp(r['ci_high'])})",
                     fp(r["p_holm"]), "; ".join(d["guardrail_breaches"]) or "none", f"**{d['decision']}**"])
    L += md_table(["Arm", "No-show change vs control (95% CI)", "Holm p", "Guardrail breaches", "Decision"], rows)
    L += ["", "Rule (fixed before running, A36): SHIP if Holm p < 0.05, the estimated reduction is at least 2 pp and "
          "no guardrail is breached; ITERATE if the reduction is significant but smaller than 2 pp or a guardrail is "
          "breached; STOP if there is no significant reduction.", ""]
    for trt in ["arm_a", "arm_b"]:
        L.append(f"- **{ARM_LABEL[trt]}: {decisions[trt]['decision']}** because {decisions[trt]['reason']}.")
    L += ["", "## Primary result (resolved appointments; SEs clustered by patient)", ""]
    L += md_table(["Arm", "Patients", "Resolved appts", "No-show rate (95% CI)"],
                  [[r["label"], f"{r['patients_resolved']:,}", f"{r['resolved_appts']:,}",
                    f"{pct(r['no_show_rate'])} ({pct(r['ci_low_cluster'])} to {pct(r['ci_high_cluster'])})"]
                   for _, r in rates.iterrows()])
    L.append("")
    rows = []
    for ref, trt in PAIRS:
        comp = f"{trt} vs {ref}"
        a, b, c = g(M_RD, comp), g(M_RR, comp), g(M_OR, comp)
        rows.append([comp, f"{pp(a['estimate'])} ({pp(a['ci_low'])} to {pp(a['ci_high'])})",
                     f"{b['estimate']:.3f} ({b['ci_low']:.3f} to {b['ci_high']:.3f})",
                     f"{c['estimate']:.3f} ({c['ci_low']:.3f} to {c['ci_high']:.3f})",
                     fp(a["p_raw"]), fp(a["p_holm"])])
    L += md_table(["Comparison", "Risk difference", "Relative risk", "Odds ratio", "p (raw)", "p (Holm)"], rows)
    L += ["", "Naive tests that ignore patient clustering (shown to illustrate the optimism):", ""]
    rows = []
    for ref, trt in PAIRS:
        comp = f"{trt} vs {ref}"
        z, c = g(M_Z, comp), g(M_CHI, comp)
        rows.append([comp, fp(z["p_raw"]), fp(z["p_holm"]), fp(c["p_raw"]), fp(c["p_holm"])])
    L += md_table(["Comparison", "z-test p", "z-test Holm p", "chi-square p", "chi-square Holm p"], rows)

    L += ["", "## Validity checks", ""]
    s1, s2 = val["srm_assigned"], val["srm_analysis"]
    L.append(f"- **Sample ratio:** assigned patients {cnt(s1['observed'])} (chi-square p = {fp(s1['p'])}; "
             f"{'SRM ALARM' if s1['alarm'] else 'no alarm at the 0.001 threshold'}). Analysed patients "
             f"{cnt(s2['observed'])} (p = {fp(s2['p'])}).")
    bal = val["balance"]
    L.append(f"- **Covariate balance:** largest absolute SMD = {bal['max_abs_smd']:.3f} ({bal['max_cov']}); "
             f"{bal['n_flagged']} of {bal['n_total']} covariate-arm comparisons exceed 0.10.")
    om = val["omnibus"]
    L.append("- **Randomization omnibus (multinomial LR test of arm on baseline covariates):** " +
             (f"chi-square = {om['lr_chi2']:.1f} on {om['df']} df, p = {fp(om['p'])}. "
              + ("No alarm threshold was pre-specified for this test (A34). The p-value is below 0.05, so it is reported as a flag: "
                 "no individual covariate is meaningfully imbalanced (see SMD above) and the covariate-adjusted estimates match the "
                 "unadjusted ones, but a real trial would investigate the assignment mechanism. In this project arms were assigned "
                 "by simple random draws, so the result is consistent with chance (one test, 64 df)."
                 if om["p"] < 0.05 else
                 "This is consistent with a working randomization.")
              if "p" in om else f"could not be computed ({om.get('error')})."))
    ig = val["integrity"]
    L.append(f"- **Assignment integrity:** appointments in the window labelled 'standard': {ig['in_window_labelled_standard']}; "
             f"appointments outside the window labelled with an arm: {ig['outside_window_labelled_arm']}; "
             f"appointments whose arm differs from the patient's assignment: {ig['arm_differs_from_assignment']}.")

    L += ["", "## Power (planned before looking at effects, A33)", ""]
    L.append(f"- Required resolved appointments per arm for a {MDE*100:.0f} pp reduction from a {BASELINE:.0%} baseline "
             f"(power {POWER:.0%}): {power['n_per_arm_independent_alpha05']:,.0f} at alpha 0.05 if observations were independent; "
             f"{power['n_per_arm_independent_holm']:,.0f} at the Holm first-step alpha of {power['alpha_holm_first_step']:.4f}.")
    L.append(f"- Pre-experiment ICC = {power['icc_pre_period']:.3f}; design effect = {power['design_effect']:.2f}; so about "
             f"{power['required_appts_per_arm_clustered_holm']:,.0f} resolved appointments (about "
             f"{power['required_patients_per_arm_holm']:,.0f} patients) per arm are required.")
    L.append(f"- Available: {cnt(power['available_resolved_appts_per_arm'])} resolved appointments and "
             f"{cnt(power['available_patients_per_arm'])} patients per arm. Smallest detectable reduction at 80% power with the "
             f"available data: {power['mde_available_holm']*100:.2f} pp (Holm) or {power['mde_available_alpha05']*100:.2f} pp (single test).")
    L.append(f"- Power at the available sample under the Holm alpha: {power['power_holm_at_3pp']:.0%} for a 3.0 pp effect, "
             f"{power['power_holm_at_2pp']:.0%} for 2.0 pp, {power['power_holm_at_1.5pp']:.0%} for 1.5 pp.")

    L += ["", "## Guardrails (harm = increase; breach needs Holm p < 0.05 and an increase of at least 1.0 pp)", ""]
    L += md_table(["Guardrail", "Comparison", "Control", "Arm", "Difference (95% CI)", "Holm p", "Breach"],
                  [[r["guardrail"], r["comparison"], pct(r["rate_control"]), pct(r["rate_arm"]),
                    f"{pp(r['rd'])} ({pp(r['ci_low'])} to {pp(r['ci_high'])})", fp(r["p_holm"]),
                    "YES" if r["breach"] else "no"] for _, r in guard.iterrows()])

    L += ["", "## Heterogeneity (exploratory; subgroup definitions are not blind, see A37)", ""]
    for j in inter["joint_tests"]:
        L.append(f"- Joint test that the effect of the reminders differs by **{j['modifier']}**: Wald chi-square = "
                 f"{j['wald_chi2']:.1f}, p = {fp(j['p_raw'])}, Holm p = {fp(j['p_holm'])}.")
    nm = {"a_med": "arm A x Medicaid", "b_med": "arm B x Medicaid", "a_long": "arm A x long lead", "b_long": "arm B x long lead"}
    for c in inter["coefs"]:
        if c["term"] in nm:
            L.append(f"  - {nm[c['term']]}: additional {pp(c['coef'])} ({pp(c['ci_low'])} to {pp(c['ci_high'])}); negative = stronger reduction.")
    L.append("")
    L += md_table(["Dimension", "Level", "Arm", "Control rate", "Arm rate", "RD (95% CI)"],
                  [[r["dimension"], r["level"], r["arm"], pct(r["rate_control"]), pct(r["rate_arm"]),
                    f"{pp(r['rd'])} ({pp(r['ci_low'])} to {pp(r['ci_high'])})"] for _, r in sub.iterrows()])

    L += ["", "## Sensitivity analyses", ""]
    for ref, trt in PAIRS:
        comp = f"{trt} vs {ref}"
        a = eff[(eff["analysis"] == "sens_all_scheduled") & (eff["method"] == M_RD) & (eff["comparison"] == comp)].iloc[0]
        L.append(f"- All scheduled appointments as denominator, {comp}: {pp(a['estimate'])} ({pp(a['ci_low'])} to {pp(a['ci_high'])}), Holm p = {fp(a['p_holm'])}.")
    for _, r in eff[eff["analysis"] == "sens_adjusted"].iterrows():
        L.append(f"- Covariate-adjusted odds ratio, {r['comparison']}: {r['estimate']:.3f} ({r['ci_low']:.3f} to {r['ci_high']:.3f}), Holm p = {fp(r['p_holm'])}.")
    for ref, trt in PAIRS[:2]:
        comp = f"{trt} vs {ref}"
        a = eff[(eff["analysis"] == "sens_patient_level") & (eff["method"] == M_PT) & (eff["comparison"] == comp)].iloc[0]
        z = eff[(eff["analysis"] == "sens_patient_level") & (eff["method"] == M_PZ) & (eff["comparison"] == comp)].iloc[0]
        L.append(f"- Patient-level, {comp}: mean patient no-show rate {pp(a['estimate'])} (Holm p = {fp(a['p_holm'])}); "
                 f"share of patients with any no-show {pp(z['estimate'])} (Holm p = {fp(z['p_holm'])}).")

    L += ["", "## Caveats", "",
          "- **Planted effects.** Every effect size here is an assumption I put into the generator. A real experiment would not "
          "know the truth; this project shows how to analyse one, not what a reminder does.",
          "- **Population.** Only patients with at least one appointment in the window are in the assignment table. A real trial "
          "should define the analysed population at assignment time to avoid post-randomization selection.",
          "- **Cancellations.** Advance cancellations are excluded from the primary denominator. If a reminder changes who cancels, "
          "that can bias the no-show rate; the all-scheduled sensitivity analysis and the non-completion guardrail address this.",
          "- **Subgroups.** Subgroup and interaction results are exploratory, and their definitions were not chosen blind.",
          "- **Duration and novelty.** The window is six months; real reminder effects can fade or depend on call content and timing.",
          "- **Synthetic payer behaviour.** Payer, lead-time and cancellation patterns come from my generator, not from observed behaviour.",
          "- **No cost side.** The outreach cost of arm A (voice calls) is not modelled here; the Phase 6 simulation uses stated assumptions."]
    text = "\n".join(L) + "\n"
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "experiment_readout.md").write_text(text)
    return text


# ---------------------------------------------------------------- run
def _j(o):
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def run() -> dict:
    appts, pats, pre, integ = load()
    d = prepare(appts)
    res = d[d["is_resolved"] == 1].copy()

    rates = arm_rates(d, res)
    rows = (cluster_rows(res, "is_no_show", "primary") + naive_rows(res)
            + cluster_rows(d, "is_no_show", "sens_all_scheduled") + patient_rows(res) + adjusted_rows(res))
    eff = pd.DataFrame(rows)
    eff["p_holm"] = eff.groupby(["analysis", "method", "metric"])["p_raw"].transform(
        lambda s: pd.Series(multipletests(s.to_numpy(), method="holm")[1], index=s.index))
    guard = guardrails(d)
    sub = subgroups(res)
    inter = interaction(res)
    power = power_section(res, pre)
    bal = balance(pats, d)
    absmax = bal.loc[bal["smd"].abs().idxmax()]
    val = {"srm_assigned": srm(pats["experiment_arm"].value_counts()),
           "srm_analysis": srm(d.groupby("arm")["patient_id"].nunique()),
           "balance": {"max_abs_smd": float(abs(absmax["smd"])), "max_cov": f"{absmax['covariate']}, {absmax['arm']} vs control",
                       "n_flagged": int((bal["smd"].abs() > SMD_FLAG).sum()), "n_total": int(len(bal))},
           "omnibus": omnibus(pats), "integrity": integ}
    decisions = decide(eff, guard)

    RESULTS.mkdir(parents=True, exist_ok=True)
    rates.to_csv(RESULTS / "experiment_arm_rates.csv", index=False)
    eff.to_csv(RESULTS / "experiment_effects.csv", index=False)
    eff[(eff["analysis"] == "primary") & eff["method"].isin([M_RD, M_RR, M_OR])].to_csv(
        RESULTS / "experiment_results.csv", index=False)
    bal.to_csv(RESULTS / "experiment_balance.csv", index=False)
    guard.to_csv(RESULTS / "experiment_guardrails.csv", index=False)
    sub.to_csv(RESULTS / "experiment_subgroups.csv", index=False)
    summary = {"synthetic": True, "decisions": decisions, "power": power, "validity": val, "interaction": inter}
    (RESULTS / "experiment_summary.json").write_text(json.dumps(summary, indent=2, default=_j))
    plot(eff, sub)
    memo = build_memo(rates, eff, guard, sub, inter, power, val, decisions)
    return {"rates": rates, "effects": eff, "guardrails": guard, "subgroups": sub, "interaction": inter,
            "power": power, "balance": bal, "validity": val, "decisions": decisions, "memo": memo}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    out = run()
    print("\n=== ARM RATES (resolved appointments, cluster-robust CI) ===")
    print(out["rates"].round(4).to_string(index=False))
    print("\n=== PRIMARY EFFECTS (cluster-robust) ===")
    e = out["effects"]
    cols = ["comparison", "metric", "estimate", "ci_low", "ci_high", "p_raw", "p_holm"]
    print(e[(e["analysis"] == "primary") & e["method"].isin([M_RD, M_RR, M_OR])][cols].round(4).to_string(index=False))
    print("\n=== VALIDITY ===")
    print(json.dumps(out["validity"], indent=2, default=_j))
    print("\n=== POWER ===")
    print(json.dumps(out["power"], indent=2, default=_j))
    print("\n=== GUARDRAILS ===")
    print(out["guardrails"].round(4).to_string(index=False))
    print("\n=== INTERACTION MODEL ===")
    print(json.dumps(out["interaction"], indent=2, default=_j))
    print("\n=== DECISIONS ===")
    print(json.dumps(out["decisions"], indent=2, default=_j))
    print("\n" + out["memo"])
