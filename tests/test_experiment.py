"""Known-answer tests for the experiment helpers in src/experiment.py."""
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src import experiment as ex


def test_sample_size_matches_textbook_formula():
    # 22% -> 20%, alpha .05, power .8: n = (1.95996+0.84162)^2 * (.22*.78 + .20*.80) / .02^2 = 6,507 (hand computed)
    n = ex.n_per_arm(0.22, 0.20, 0.05, 0.80)
    assert n == pytest.approx(6506.7, abs=1.0)


def test_mde_inverts_sample_size():
    n = ex.n_per_arm(0.22, 0.20, 0.05, 0.80)
    assert ex.mde_for_n(n, 0.22, 0.05, 0.80) == pytest.approx(0.02, abs=1e-4)


def test_power_is_alpha_when_effect_is_zero_and_rises_with_effect():
    assert ex.power_at(0.0, 5000, 0.22, 0.05) == pytest.approx(0.025, abs=1e-3)   # two-sided: only the one tail counts
    assert ex.power_at(0.03, 5000, 0.22, 0.05) > ex.power_at(0.01, 5000, 0.22, 0.05)


def test_srm_detects_imbalance_and_accepts_balance():
    ok = ex.srm(pd.Series({"control": 1000, "arm_a": 1000, "arm_b": 1000}))
    assert ok["p"] == pytest.approx(1.0) and not ok["alarm"]
    bad = ex.srm(pd.Series({"control": 1500, "arm_a": 1000, "arm_b": 500}))
    assert bad["alarm"]


def test_icc_is_zero_without_clustering_and_high_with_it():
    rng = np.random.default_rng(1)
    g = np.repeat(np.arange(500), 5)
    y_indep = (rng.random(len(g)) < 0.3).astype(float)
    assert ex.icc_anova(y_indep, g) < 0.05
    y_clustered = np.repeat((rng.random(500) < 0.3).astype(float), 5)   # whole patient shares one outcome
    assert ex.icc_anova(y_clustered, g) > 0.9


def test_contrast_risk_difference_known_answer():
    # control 2/10 = 0.2, arm_a 1/10 = 0.1 -> RD = -0.1 (each row its own patient)
    df = pd.DataFrame({
        "arm": ["control"] * 10 + ["arm_a"] * 10,
        "pid": np.arange(20),
        "y": [1, 1] + [0] * 8 + [1] + [0] * 9,
    })
    c = ex.contrast(df, "y", "control", "arm_a", full=False)
    assert c["rate_ref"] == pytest.approx(0.2) and c["rate_trt"] == pytest.approx(0.1)
    assert c["rd"] == pytest.approx(-0.1)


def test_decision_rule_ship_iterate_stop():
    def eff(est, p_holm):
        rows = []
        for comp in ("arm_a vs control", "arm_b vs control"):
            rows.append({"analysis": "primary", "method": ex.M_RD, "comparison": comp,
                         "estimate": est[comp], "p_holm": p_holm[comp]})
        return pd.DataFrame(rows)

    no_breach = pd.DataFrame({"comparison": ["arm_a vs control", "arm_b vs control"],
                              "guardrail": ["g", "g"], "breach": [False, False]})
    d = ex.decide(eff({"arm_a vs control": -0.03, "arm_b vs control": -0.015},
                      {"arm_a vs control": 0.001, "arm_b vs control": 0.001}), no_breach)
    assert d["arm_a"]["decision"] == "SHIP" and d["arm_b"]["decision"] == "ITERATE"
    d = ex.decide(eff({"arm_a vs control": -0.03, "arm_b vs control": -0.03},
                      {"arm_a vs control": 0.001, "arm_b vs control": 0.30}), no_breach)
    assert d["arm_b"]["decision"] == "STOP"
    breach = no_breach.assign(breach=[True, False])
    d = ex.decide(eff({"arm_a vs control": -0.03, "arm_b vs control": -0.03},
                      {"arm_a vs control": 0.001, "arm_b vs control": 0.001}), breach)
    assert d["arm_a"]["decision"] == "ITERATE"   # significant and large, but a guardrail is breached
