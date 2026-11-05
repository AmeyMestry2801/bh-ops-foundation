"""Phase 6: no-show model ladder (M0 base rate, M1 logistic, M2 XGBoost) with a pre-specified promotion rule.

Run:  python -m src.model        (after: python -m src.pipeline and python -m src.experiment)
Rules: docs/leakage_audit.md and docs/assumptions.md A43-A50, written before this script was run.
ALL DATA IS SYNTHETIC; several drivers were planted by src/generate_data.py.
"""
import json
import logging
import time

import matplotlib
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import loguniform
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, precision_recall_curve,
                             roc_auc_score)
from sklearn.model_selection import PredefinedSplit, RandomizedSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from statsmodels.stats.multitest import multipletests
from xgboost import XGBClassifier

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src import features as F  # noqa: E402
from src.config import FIGURES, RESULTS, SEED  # noqa: E402

log = logging.getLogger("model")

CAPACITY = 0.20
MIN_GAIN = 0.02
B_VAL, B_TEST = 1000, 500
C_GRID = [0.001, 0.01, 0.1, 1, 10]
N_ITER = 25


def _j(o):
    return o.item() if hasattr(o, "item") else str(o)


# ---------------------------------------------------------------- preprocessing and models
def make_pre(kind):
    if kind == "logit":
        num = Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)), ("sc", StandardScaler())])
    else:
        num = "passthrough"          # XGBoost handles NaN natively
    return ColumnTransformer([("num", num, F.NUM),
                              ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), F.CAT)])


def orig_feature(name):
    base = name.split("__", 1)[1]
    if name.startswith("num__"):
        return base.replace("missingindicator_", "")
    for c in F.CAT:
        if base.startswith(c + "_"):
            return c
    return base


def fit_logit(X, y, C):
    return LogisticRegression(C=C, max_iter=2000).fit(X, y)


def xgb_model(params):
    return XGBClassifier(objective="binary:logistic", eval_metric="aucpr", tree_method="hist",
                         random_state=SEED, **params)


def search_xgb(Xtr, ytr, Xva, yva):
    X = np.vstack([Xtr, Xva])
    y = np.concatenate([ytr, yva])
    fold = np.r_[np.full(len(ytr), -1), np.zeros(len(yva))]
    dist = {"max_depth": [2, 3, 4, 5, 6], "learning_rate": loguniform(0.02, 0.2),
            "n_estimators": [100, 200, 300, 400], "subsample": [0.6, 0.8, 1.0],
            "colsample_bytree": [0.6, 0.8, 1.0], "min_child_weight": [1, 5, 10, 20],
            "reg_lambda": loguniform(0.1, 20)}
    rs = RandomizedSearchCV(xgb_model({}), dist, n_iter=N_ITER, scoring="average_precision",
                            cv=PredefinedSplit(fold), refit=False, random_state=SEED, n_jobs=1)
    rs.fit(X, y)
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in rs.best_params_.items()}, float(rs.best_score_)


# ---------------------------------------------------------------- metrics
def metrics(y, p):
    return {"pr_auc": float(average_precision_score(y, p)), "roc_auc": float(roc_auc_score(y, p)),
            "brier": float(brier_score_loss(y, p))}


def cluster_boot(y, probs, codes, B, rng):
    """Patient-cluster bootstrap of PR-AUC via row weights (a patient drawn k times gets weight k)."""
    n_p = int(codes.max()) + 1
    out = {k: np.empty(B) for k in probs}
    for b in range(B):
        w = np.bincount(rng.integers(0, n_p, n_p), minlength=n_p)[codes].astype(float)
        for k, p in probs.items():
            out[k][b] = average_precision_score(y, p, sample_weight=w)
    return out


def topk(y, s, frac):
    k = int(round(frac * len(y)))
    idx = np.argsort(-s, kind="stable")[:k]
    flagged = np.zeros(len(y), dtype=int)
    flagged[idx] = 1
    prec, rec = float(y[idx].mean()), float(y[idx].sum() / y.sum())
    return {"k": k, "precision": prec, "recall": rec, "lift": prec / float(y.mean())}, flagged


def lift_table(y, s, model):
    d = pd.DataFrame({"y": y, "s": s}).sort_values("s", ascending=False, kind="stable").reset_index(drop=True)
    d["decile"] = np.arange(len(d)) * 10 // len(d) + 1
    g = d.groupby("decile").agg(n=("y", "size"), no_shows=("y", "sum")).reset_index()
    base = y.mean()
    g["no_show_rate"] = g["no_shows"] / g["n"]
    g["lift"] = g["no_show_rate"] / base
    g["cum_capture"] = g["no_shows"].cumsum() / y.sum()
    g["cum_lift"] = g["cum_capture"] / (g["n"].cumsum() / len(y))
    g.insert(0, "model", model)
    return g


# ---------------------------------------------------------------- fairness, SHAP, simulation
def fairness(te, y, flagged):
    rows, tests = [], []
    for col in ["payer_type", "age_band"]:
        for lvl in sorted(te[col].unique()):
            m = (te[col] == lvl).to_numpy()
            pos, neg = m & (y == 1), m & (y == 0)
            rows.append({"variable": col, "level": lvl, "n": int(m.sum()), "no_show_rate": float(y[m].mean()),
                         "flag_rate": float(flagged[m].mean()),
                         "precision_flagged": float(y[m & (flagged == 1)].mean()) if (m & (flagged == 1)).any() else np.nan,
                         "false_negative_rate": float((flagged[pos] == 0).mean()) if pos.any() else np.nan,
                         "false_positive_rate": float((flagged[neg] == 1).mean()) if neg.any() else np.nan})
        d = pd.DataFrame({"g": te[col].to_numpy(), "y": y, "f": flagged})
        for name, sub, outcome in (("false-negative rate", d[d.y == 1], d[d.y == 1].f == 0),
                                   ("false-positive rate", d[d.y == 0], d[d.y == 0].f == 1)):
            ct = pd.crosstab(sub["g"], outcome)
            try:
                chi2, p, _, _ = stats.chi2_contingency(ct, correction=False)
                tests.append({"variable": col, "error_rate": name, "chi2": float(chi2), "p_raw": float(p)})
            except ValueError:
                tests.append({"variable": col, "error_rate": name, "chi2": np.nan, "p_raw": np.nan})
    t = pd.DataFrame(tests)
    ok = t["p_raw"].notna()
    t.loc[ok, "p_holm"] = multipletests(t.loc[ok, "p_raw"].to_numpy(), method="holm")[1]
    return pd.DataFrame(rows), t


def shap_section(final_name, model, pre, te, ref_mean, rng):
    idx = rng.choice(len(te), size=min(3000, len(te)), replace=False)
    Xs = pre.transform(te.iloc[idx][F.FEATURES])
    names = list(pre.get_feature_names_out())
    method, shap_mod = "", None
    if final_name == "M2":
        try:
            import shap as shap_mod
            sv = np.asarray(shap_mod.TreeExplainer(model).shap_values(Xs))
            if sv.ndim == 3:
                sv = sv[..., -1]
            method = "shap.TreeExplainer"
        except Exception as e:  # noqa: BLE001
            import xgboost as xgb
            sv = model.get_booster().predict(xgb.DMatrix(Xs), pred_contribs=True)[:, :-1]
            method = f"xgboost pred_contribs (TreeSHAP); shap library failed: {str(e)[:80]}"
    else:
        sv = (Xs - ref_mean) * model.coef_[0]
        method = "exact linear SHAP (coefficient x centered feature), log-odds scale"
    groups = {}
    for i, n in enumerate(names):
        groups.setdefault(orig_feature(n), []).append(i)
    imp = pd.DataFrame({"feature": list(groups),
                        "mean_abs_shap": [float(np.abs(sv[:, c].sum(axis=1)).mean()) for c in groups.values()]})
    imp = imp.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(imp["feature"][::-1], imp["mean_abs_shap"][::-1], color="#4C78A8")
    ax.set_xlabel("mean |SHAP| (log-odds); one-hot levels summed per feature")
    ax.set_title(f"SHAP importance, final model {final_name} (synthetic data)")
    fig.tight_layout()
    fig.savefig(FIGURES / "shap_importance.png", dpi=130)
    plt.close(fig)
    try:
        if shap_mod is None:
            import shap as shap_mod
        shap_mod.summary_plot(sv, Xs, feature_names=names, show=False, max_display=15)
        plt.tight_layout()
        plt.savefig(FIGURES / "shap_summary.png", dpi=130)
        plt.close()
    except Exception:  # noqa: BLE001
        plt.close("all")
    return imp, method


def simulate(y, flagged):
    eff = pd.read_csv(RESULTS / "experiment_effects.csv")
    a = eff[(eff["analysis"] == "primary") & (eff["comparison"] == "arm_a vs control")
            & eff["method"].str.startswith("cluster-robust")]
    rd = a[a["metric"] == "risk difference"].iloc[0]
    rr = a[a["metric"] == "relative risk"].iloc[0]
    n, k = len(y), int(flagged.sum())
    ns_flag, base = int(y[flagged == 1].sum()), float(y.mean())

    def row(label, prevented, lo, hi):
        return {"scenario": label, "prevented": float(prevented), "prevented_low": float(lo),
                "prevented_high": float(hi), "per_1000_resolved": float(prevented / n * 1000),
                "calls_per_prevented": float(k / prevented)}

    red, red_lo, red_hi = -rd["estimate"], -rd["ci_high"], -rd["ci_low"]
    rrp, rr_lo, rr_hi = 1 - rr["estimate"], 1 - rr["ci_high"], 1 - rr["ci_low"]
    rows = [row("A: uniform absolute reduction, model top 20%", k * red, k * red_lo, k * red_hi),
            row("A: uniform absolute reduction, random 20%", k * red, k * red_lo, k * red_hi),
            row("B: relative reduction, model top 20%", ns_flag * rrp, ns_flag * rr_lo, ns_flag * rr_hi),
            row("B: relative reduction, random 20%", k * base * rrp, k * base * rr_lo, k * base * rr_hi)]
    return {"n_resolved": n, "n_called": k, "observed_no_shows_among_called": ns_flag,
            "observed_no_shows_total": int(y.sum()),
            "arm_a_rd": float(rd["estimate"]), "arm_a_rd_ci": [float(rd["ci_low"]), float(rd["ci_high"])],
            "arm_a_rr": float(rr["estimate"]), "arm_a_rr_ci": [float(rr["ci_low"]), float(rr["ci_high"])],
            "rows": rows}


# ---------------------------------------------------------------- main
def run() -> dict:
    t0 = time.perf_counter()
    rng = np.random.default_rng(SEED)
    df = F.load()
    tr, va, te = (df[df["split"] == s].reset_index(drop=True) for s in ("train", "val", "test"))
    ytr, yva, yte = (x[F.TARGET].to_numpy() for x in (tr, va, te))
    log.info("rows: total=%d train=%d val=%d test=%d", len(df), len(tr), len(va), len(te))

    # ---- model selection on validation (train-only fits)
    pre1 = make_pre("logit").fit(tr[F.FEATURES])
    X1tr, X1va = pre1.transform(tr[F.FEATURES]), pre1.transform(va[F.FEATURES])
    grid = [{"C": C, "val_pr_auc": float(average_precision_score(yva, fit_logit(X1tr, ytr, C).predict_proba(X1va)[:, 1]))}
            for C in C_GRID]
    best_c = max(grid, key=lambda g: g["val_pr_auc"])["C"]
    p1_va = fit_logit(X1tr, ytr, best_c).predict_proba(X1va)[:, 1]

    pre2 = make_pre("xgb").fit(tr[F.FEATURES])
    X2tr, X2va = pre2.transform(tr[F.FEATURES]), pre2.transform(va[F.FEATURES])
    best_params, search_score = search_xgb(X2tr, ytr, X2va, yva)
    p2_va = xgb_model(best_params).fit(X2tr, ytr).predict_proba(X2va)[:, 1]
    p0_va = np.full(len(yva), ytr.mean())
    log.info("selection done (%.0fs)", time.perf_counter() - t0)

    # ---- promotion rule (A46)
    codes_va = pd.factorize(va["patient_id"])[0]
    boot = cluster_boot(yva, {"M1": p1_va, "M2": p2_va}, codes_va, B_VAL, rng)
    diff = boot["M2"] - boot["M1"]
    gain = float(average_precision_score(yva, p2_va) - average_precision_score(yva, p1_va))
    d_lo, d_hi = (float(x) for x in np.percentile(diff, [2.5, 97.5]))
    promote = bool(gain >= MIN_GAIN and d_lo > 0)
    final_name = "M2" if promote else "M1"
    promotion = {"val_pr_auc_M0": float(average_precision_score(yva, p0_va)),
                 "val_pr_auc_M1": float(average_precision_score(yva, p1_va)),
                 "val_pr_auc_M2": float(average_precision_score(yva, p2_va)),
                 "gain_M2_minus_M1": gain, "ci95_low": d_lo, "ci95_high": d_hi,
                 "rule": f"promote M2 if gain >= {MIN_GAIN} and CI lower bound > 0",
                 "promote_M2": promote, "final_model": final_name}

    # ---- refit on train+val, evaluate on test ONCE
    trva = pd.concat([tr, va], ignore_index=True)
    ytv = trva[F.TARGET].to_numpy()
    pre1f = make_pre("logit").fit(trva[F.FEATURES])
    X1tv = pre1f.transform(trva[F.FEATURES])
    m1 = fit_logit(X1tv, ytv, best_c)
    pre2f = make_pre("xgb").fit(trva[F.FEATURES])
    m2 = xgb_model(best_params).fit(pre2f.transform(trva[F.FEATURES]), ytv)
    p1_te = m1.predict_proba(pre1f.transform(te[F.FEATURES]))[:, 1]
    p2_te = m2.predict_proba(pre2f.transform(te[F.FEATURES]))[:, 1]
    p0_te = np.full(len(yte), ytv.mean())
    probs_te = {"M0": p0_te, "M1": p1_te, "M2": p2_te}
    p_final = probs_te[final_name]

    codes_te = pd.factorize(te["patient_id"])[0]
    boot_te = cluster_boot(yte, probs_te, codes_te, B_TEST, rng)
    rows, flags = [], {}
    for k, p in probs_te.items():
        lo, hi = np.percentile(boot_te[k], [2.5, 97.5])
        r = {"model": k, "final": k == final_name, **metrics(yte, p), "pr_auc_ci_low": float(lo), "pr_auc_ci_high": float(hi)}
        if k != "M0":
            tk, flags[k] = topk(yte, p, CAPACITY)
            r.update({"precision_at_20pct": tk["precision"], "recall_at_20pct": tk["recall"], "lift_at_20pct": tk["lift"]})
        rows.append(r)
    test_metrics = pd.DataFrame(rows)
    td = boot_te["M2"] - boot_te["M1"]
    test_diff = {"pr_auc_M2_minus_M1": float(average_precision_score(yte, p2_te) - average_precision_score(yte, p1_te)),
                 "ci95": [float(x) for x in np.percentile(td, [2.5, 97.5])], "note": "informational only; the decision used validation"}
    flagged = flags[final_name]

    lifts = pd.concat([lift_table(yte, p1_te, "M1"), lift_table(yte, p2_te, "M2")], ignore_index=True)
    lifts["is_final"] = lifts["model"] == final_name
    cell = ((te["payer_type"] == "Medicaid") & (te["modality"] == "in_person") & (te["lead_days"] > 21)).to_numpy()
    cell_check = {nm: {"n": int(m.sum()), "observed": float(yte[m].mean()), "mean_pred_M1": float(p1_te[m].mean()),
                       "mean_pred_M2": float(p2_te[m].mean())} for nm, m in (("planted_cell", cell), ("everyone_else", ~cell))}

    # ---- odds ratios, fairness, SHAP, simulation
    names1 = pre1f.get_feature_names_out()
    orr = pd.DataFrame({"feature": names1, "coef": m1.coef_[0], "odds_ratio": np.exp(m1.coef_[0])})
    orr["abs_log_or"] = orr["coef"].abs()
    orr = orr.sort_values("abs_log_or", ascending=False).drop(columns="abs_log_or").reset_index(drop=True)
    fair, fair_tests = fairness(te, yte, flagged)
    if final_name == "M2":
        imp, shap_method = shap_section("M2", m2, pre2f, te, None, rng)
    else:
        imp, shap_method = shap_section("M1", m1, pre1f, te, X1tv.mean(axis=0), rng)
    sim = simulate(yte, flagged)

    # ---- figures
    fig, axes = plt.subplots(1, 3, figsize=(17, 5))
    ax = axes[0]
    for k, p, c in (("M1", p1_te, "#4C78A8"), ("M2", p2_te, "#E45756")):
        fp_, mp_ = calibration_curve(yte, p, n_bins=10, strategy="quantile")
        ax.plot(mp_, fp_, "o-", label=k, color=c)
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("mean predicted risk")
    ax.set_ylabel("observed no-show rate")
    ax.set_title("Calibration (test, 10 quantile bins)")
    ax.legend()
    ax = axes[1]
    lt = lifts[lifts["model"] == final_name]
    ax.plot(np.r_[0, lt["decile"] * 10], np.r_[0, lt["cum_capture"] * 100], "o-", label=f"{final_name} (final)")
    ax.plot([0, 100], [0, 100], "k--", lw=1, label="random")
    ax.axvline(20, color="gray", ls=":")
    ax.set_xlabel("% of appointments called (highest risk first)")
    ax.set_ylabel("% of no-shows captured")
    ax.set_title("Cumulative gain (test)")
    ax.legend()
    ax = axes[2]
    for k, p, c in (("M1", p1_te, "#4C78A8"), ("M2", p2_te, "#E45756")):
        pr, rc, _ = precision_recall_curve(yte, p)
        ax.plot(rc, pr, label=k, color=c)
    ax.axhline(yte.mean(), color="k", ls="--", lw=1, label="base rate (M0)")
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_title("Precision-recall (test)")
    ax.legend()
    fig.suptitle("No-show model evaluation on SYNTHETIC data")
    fig.tight_layout()
    fig.savefig(FIGURES / "model_eval.png", dpi=130)
    plt.close(fig)

    # ---- save
    RESULTS.mkdir(parents=True, exist_ok=True)
    test_metrics.to_csv(RESULTS / "model_test_metrics.csv", index=False)
    lifts.to_csv(RESULTS / "lift_table.csv", index=False)
    orr.to_csv(RESULTS / "model_odds_ratios.csv", index=False)
    imp.to_csv(RESULTS / "shap_importance.csv", index=False)
    fair.to_csv(RESULTS / "fairness_slices.csv", index=False)
    fair_tests.to_csv(RESULTS / "fairness_tests.csv", index=False)
    sc = []
    for split, part, a1, a2, a0, fl in (("val", va, p1_va, p2_va, p0_va, None), ("test", te, p1_te, p2_te, p0_te, flagged)):
        s = part[["appointment_id", "patient_id", "appt_date"]].copy()
        s["split"], s["y_no_show"] = split, part[F.TARGET].to_numpy()
        s["score_m0"], s["score_m1"], s["score_m2"] = a0, a1, a2
        s["score_final"] = a2 if final_name == "M2" else a1
        s["flagged_top20"] = fl if fl is not None else np.nan
        sc.append(s)
    pd.concat(sc, ignore_index=True).to_csv(RESULTS / "model_scores.csv", index=False)
    summary = {"synthetic": True, "n_rows": {"total": len(df), "train": len(tr), "val": len(va), "test": len(te)},
               "base_rate": {"train": float(ytr.mean()), "val": float(yva.mean()), "test": float(yte.mean())},
               "selection": {"logit_grid": grid, "best_C": best_c, "xgb_best_params": best_params,
                             "xgb_search_val_pr_auc": search_score, "xgb_draws": N_ITER},
               "promotion": promotion, "test_metrics": test_metrics.to_dict("records"), "test_diff_M2_M1": test_diff,
               "planted_cell_check": cell_check, "shap_method": shap_method, "simulation": sim,
               "runtime_seconds": round(time.perf_counter() - t0, 1)}
    (RESULTS / "model_metrics.json").write_text(json.dumps(summary, indent=2, default=_j))
    return {"summary": summary, "test_metrics": test_metrics, "lifts": lifts, "odds": orr, "fairness": fair,
            "fairness_tests": fair_tests, "shap": imp, "final": final_name}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    o = run()
    s = o["summary"]
    print("\n=== ROWS / BASE RATES ===")
    print(json.dumps({"rows": s["n_rows"], "base_rate": s["base_rate"]}, indent=2))
    print("\n=== SELECTION (validation) ===")
    print(json.dumps(s["selection"], indent=2, default=_j))
    print("\n=== PROMOTION DECISION ===")
    print(json.dumps(s["promotion"], indent=2))
    print("\n=== TEST METRICS (touched once) ===")
    print(o["test_metrics"].round(4).to_string(index=False))
    print("\ntest M2-M1 PR-AUC (informational):", json.dumps(s["test_diff_M2_M1"]))
    print("\n=== LIFT BY DECILE, FINAL MODEL (test) ===")
    print(o["lifts"][o["lifts"]["model"] == o["final"]].round(3).to_string(index=False))
    print("\n=== PLANTED CELL CHECK (diagnostic; uses author knowledge of the generator) ===")
    print(json.dumps(s["planted_cell_check"], indent=2))
    print("\n=== M1 ODDS RATIOS (top 12 by effect; numeric = per 1 SD; one-hot levels are not vs a single reference) ===")
    print(o["odds"].head(12).round(3).to_string(index=False))
    print(f"\n=== SHAP IMPORTANCE ({s['shap_method']}) ===")
    print(o["shap"].round(4).to_string(index=False))
    print("\n=== FAIRNESS SLICES (final model, top 20%) ===")
    print(o["fairness"].round(3).to_string(index=False))
    print(o["fairness_tests"].round(4).to_string(index=False))
    print("\n=== SIMULATION (test period, synthetic; see A49) ===")
    print(json.dumps(s["simulation"], indent=2))
    print("\nruntime_seconds:", s["runtime_seconds"])
