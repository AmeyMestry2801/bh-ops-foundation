"""Phase 4: EDA + association tests on resolved appointments (standard + control arms only).

Run:  python -m src.eda        (after: python -m src.pipeline)
Outputs: results/eda_rates.csv, results/eda_tests.csv, reports/figures/eda_noshow_drivers.png,
         docs/eda_findings.md
Tests: chi-square of independence + bias-corrected Cramer's V (also on one-appointment-per-patient),
Mann-Whitney U (rank-biserial), Spearman. Holm correction across ALL tests in this script.
ALL DATA IS SYNTHETIC; several drivers were planted by src/generate_data.py.
"""
import logging

import duckdb
import matplotlib
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.config import FIGURES, RESULTS, ROOT, SEED, WAREHOUSE  # noqa: E402

log = logging.getLogger("eda")

SQL = """
select f.appointment_id, f.patient_id, f.appt_date, f.appt_dow, f.appt_hour, f.lead_days,
       f.lead_bucket, f.modality, f.status, f.reminder_arm, f.is_no_show,
       p.payer_type, p.age_band, p.prior_no_show_count, p.phq9_total, p.gad7_total, p.acuity
from marts.fact_appointment f
join marts.dim_patient p on f.patient_id = p.patient_id
where f.is_resolved = 1 and f.reminder_arm in ('standard', 'control')
"""

LEAD_ORDER = ["0-1", "2-7", "8-14", "15-21", "22-30", "31+"]
DOW = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"}
DIMS = {  # column -> (label, level order or None)
    "lead_bucket": ("Lead time (days)", LEAD_ORDER),
    "payer_type": ("Payer", None),
    "modality": ("Modality", None),
    "dow": ("Day of week", list(DOW.values())),
    "age_band": ("Age band", ["18-24", "25-34", "35-49", "50-64", "65+"]),
    "prior_bucket": ("Prior no-shows", ["0", "1", "2", "3+"]),
    "acuity": ("Acuity", ["low", "moderate", "high"]),
    "appt_hour": ("Appointment hour", None),
    "risk_cell": ("Medicaid x in-person x lead>21d", ["other", "cell"]),
}
PLOT_DIMS = ["lead_bucket", "payer_type", "modality", "dow", "age_band", "prior_bucket"]
CONT = {"lead_days": "Lead time (days)", "prior_no_show_count": "Prior no-show count",
        "phq9_total": "PHQ-9 total", "gad7_total": "GAD-7 total"}


def load() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute(SQL).df()
    con.close()
    df["dow"] = df["appt_dow"].map(DOW)
    df["prior_bucket"] = np.minimum(df["prior_no_show_count"], 3).astype(int).astype(str).replace({"3": "3+"})
    df["appt_hour"] = df["appt_hour"].astype(int).astype(str).str.zfill(2)
    df["risk_cell"] = np.where((df["payer_type"] == "Medicaid") & (df["modality"] == "in_person")
                               & (df["lead_days"] > 21), "cell", "other")
    for c in ("phq9_total", "gad7_total"):
        df[c] = df[c].astype("float64")
    return df


def rate_table(df, dim):
    g = df.groupby(dim)["is_no_show"].agg(n="size", no_shows="sum").reset_index().rename(columns={dim: "level"})
    lo, hi = proportion_confint(g["no_shows"], g["n"], method="wilson")
    g["rate"], g["ci_low"], g["ci_high"] = g["no_shows"] / g["n"], lo, hi
    order = DIMS[dim][1]
    if order:
        g["level"] = pd.Categorical(g["level"], categories=order, ordered=True)
        g = g.sort_values("level")
    g["level"] = g["level"].astype(str)
    g.insert(0, "dimension", dim)
    return g.reset_index(drop=True)


def cramers_v(table):
    chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
    n = table.to_numpy().sum()
    r, k = table.shape
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))   # Bergsma bias correction
    rc, kc = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
    v = float(np.sqrt(phi2 / max(1e-12, min(kc - 1, rc - 1))))
    return float(chi2), float(p), int(dof), v, int(n)


def run_tests(df):
    one = df.groupby("patient_id").sample(n=1, random_state=SEED)
    rows = []
    for dim, (label, _) in DIMS.items():
        chi2, p, dof, v, n = cramers_v(pd.crosstab(df[dim], df["is_no_show"]))
        v1 = cramers_v(pd.crosstab(one[dim], one["is_no_show"]))[3]
        rows.append({"family": "chi-square", "variable": label, "statistic": chi2, "effect_name": "cramers_v",
                     "effect": v, "n": n, "p_raw": p, "v_one_per_patient": v1})
    y = df["is_no_show"] == 1
    for col, label in CONT.items():
        x = df[col]
        ok = x.notna()
        a, b = x[ok & y], x[ok & ~y]
        u, p = stats.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic")
        cles = float(u / (len(a) * len(b)))
        rows.append({"family": "mann-whitney", "variable": label, "statistic": float(u),
                     "effect_name": "rank_biserial", "effect": 2 * cles - 1, "n": int(ok.sum()), "p_raw": float(p),
                     "median_noshow": float(a.median()), "median_other": float(b.median())})
        rho, p = stats.spearmanr(x[ok], df.loc[ok, "is_no_show"])
        rows.append({"family": "spearman", "variable": label, "statistic": float(rho),
                     "effect_name": "rho", "effect": float(rho), "n": int(ok.sum()), "p_raw": float(p)})
    t = pd.DataFrame(rows)
    t["p_holm"] = multipletests(t["p_raw"].to_numpy(), method="holm")[1]
    t["significant_holm_0.05"] = t["p_holm"] < 0.05
    return t


def fmt_p(p):
    return "<1e-300" if p < 1e-300 else f"{p:.2e}"


def strength(v):
    return "negligible" if v < 0.05 else "weak" if v < 0.10 else "modest" if v < 0.20 else "notable"


def plot(rates, overall):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, dim in zip(axes.ravel(), PLOT_DIMS):
        r = rates[rates["dimension"] == dim]
        err = np.vstack([r["rate"] - r["ci_low"], r["ci_high"] - r["rate"]])
        ax.bar(r["level"], r["rate"], yerr=err, capsize=3, color="#4C78A8")
        ax.axhline(overall, color="red", ls="--", lw=1)
        ax.set_title(DIMS[dim][0])
        ax.set_ylabel("no-show rate")
        ax.set_ylim(0, max(0.45, r["ci_high"].max() * 1.1))
        ax.tick_params(axis="x", rotation=30)
    fig.suptitle("No-show rate by driver (synthetic data; standard + control arms; red = overall; 95% Wilson CI)")
    fig.tight_layout()
    fig.savefig(FIGURES / "eda_noshow_drivers.png", dpi=130)
    plt.close(fig)


def findings(df, rates, tests, overall):
    L = ["# EDA Findings (plain language)", "",
         "> ALL DATA IS SYNTHETIC. Several drivers below were PLANTED by src/generate_data.py, so this "
         "demonstrates the method; it is not evidence about real patients.", "",
         f"Population: {len(df):,} resolved appointments (completed, no-show, late-cancel) in the standard and "
         f"control reminder arms. Overall no-show rate: {overall:.1%}. Holm correction applied across all "
         f"{len(tests)} tests in this script.", "", "## Association with no-show (chi-square + Cramer's V)", ""]
    ch = tests[tests["family"] == "chi-square"].sort_values("effect", ascending=False)
    inv = {v[0]: k for k, v in DIMS.items()}
    for _, t in ch.iterrows():
        r = rates[(rates["dimension"] == inv[t["variable"]]) & (rates["n"] >= 500)]
        lo, hi = r.loc[r["rate"].idxmin()], r.loc[r["rate"].idxmax()]
        L.append(f"- **{t['variable']}**: no-show ranges from {lo['rate']:.1%} ({lo['level']}) to "
                 f"{hi['rate']:.1%} ({hi['level']}). Cramer's V = {t['effect']:.3f} ({strength(t['effect'])}); "
                 f"Holm p = {fmt_p(t['p_holm'])}. One-appointment-per-patient check: V = {t['v_one_per_patient']:.3f}.")
    c = rates[rates["dimension"] == "risk_cell"].set_index("level")
    rr = c.loc["cell", "rate"] / c.loc["other", "rate"]
    L += ["", "## The planted three-way pattern", "",
          f"Medicaid patients booked more than 21 days ahead for in-person visits no-show {c.loc['cell', 'rate']:.1%} "
          f"of the time (n={int(c.loc['cell', 'n']):,}) versus {c.loc['other', 'rate']:.1%} for everyone else, "
          f"a risk ratio of {rr:.2f}. I built this interaction into the generator, so a flexible model "
          "should be able to find it in Phase 6; a plain logistic regression cannot without an added term.",
          "", "## Distribution differences (Mann-Whitney) and monotone trends (Spearman)", ""]
    for _, t in tests[tests["family"] == "mann-whitney"].iterrows():
        s = tests[(tests["family"] == "spearman") & (tests["variable"] == t["variable"])].iloc[0]
        L.append(f"- **{t['variable']}**: median {t['median_noshow']:.1f} for no-shows vs {t['median_other']:.1f} "
                 f"for others; rank-biserial = {t['effect']:.3f}, Spearman rho = {s['effect']:.3f}; "
                 f"Holm p = {fmt_p(t['p_holm'])}.")
    L += ["", "## How to read this", "",
          "- With this many rows, tiny differences are statistically significant. Judge importance by effect size.",
          "- Appointments from the same patient are correlated, so p-values here are optimistic. The "
          "one-per-patient Cramer's V is the sanity check; the Phase 5 experiment analysis uses patient-level units.",
          "- These are associations in synthetic data, not causal effects. Variables overlap (e.g. payer and "
          "lead time), so single-variable rates do not isolate any one driver; Phase 6 models them jointly.",
          "- Cramer's V uses the Bergsma bias correction. Strength labels (<0.05 negligible, <0.10 weak, "
          "<0.20 modest, else notable) are my own rule of thumb."]
    (ROOT / "docs").mkdir(exist_ok=True)
    text = "\n".join(L) + "\n"
    (ROOT / "docs" / "eda_findings.md").write_text(text)
    return text


def run() -> dict:
    df = load()
    overall = float(df["is_no_show"].mean())
    rates = pd.concat([rate_table(df, d) for d in DIMS], ignore_index=True)
    tests = run_tests(df)
    RESULTS.mkdir(parents=True, exist_ok=True)
    rates.to_csv(RESULTS / "eda_rates.csv", index=False)
    tests.to_csv(RESULTS / "eda_tests.csv", index=False)
    plot(rates, overall)
    text = findings(df, rates, tests, overall)
    return {"df_rows": len(df), "overall": overall, "rates": rates, "tests": tests, "findings": text}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = run()
    print(f"\nrows={out['df_rows']:,}  overall no-show={out['overall']:.4f}\n")
    cols = ["family", "variable", "effect_name", "effect", "n", "p_holm", "v_one_per_patient"]
    pd.set_option("display.width", 200)
    print(out["tests"][cols].round(4).to_string(index=False))
    print("\n" + out["findings"])
