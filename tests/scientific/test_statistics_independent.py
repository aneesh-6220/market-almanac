"""Independent numerical checks of the inference machinery.

Each test compares Market Almanac's implementation with a hand calculation or with a different
implementation (statsmodels), never with Market Almanac itself.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.multitest import multipletests

from market_almanac.evaluation.backtest import common_sample
from market_almanac.evaluation.inference import (
    diebold_mariano,
    holm_adjust,
    moving_block_bootstrap_ratio,
    newey_west_variance,
)
from market_almanac.evaluation.metrics import classification_metrics, regression_metrics


def test_newey_west_variance_by_hand():
    # d = 1,2,3,4: deviations -1.5,-.5,.5,1.5; gamma0 = 5/4; gamma1 = (0.75-0.25+0.75)/4 = 0.3125
    # Bartlett weight for lag 1 of 1 is 1/2: variance = 1.25 + 2*0.5*0.3125 = 1.5625
    d = np.array([1.0, 2.0, 3.0, 4.0])
    assert newey_west_variance(d, 0) == pytest.approx(1.25)
    assert newey_west_variance(d, 1) == pytest.approx(1.5625)


def _ar1(n: int, rho: float, rng: np.random.Generator, mean: float = 0.0) -> np.ndarray:
    e = rng.normal(size=n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return x + mean


@pytest.mark.parametrize("h", [1, 3])
def test_diebold_mariano_matches_statsmodels_hac(h):
    rng = np.random.default_rng(11)
    T = 68
    d = _ar1(T, 0.4, rng, 0.15)
    dates = pd.date_range("2021-01-01", periods=T, freq="MS")
    # one row per month, loss_a - loss_b = d
    res = diebold_mariano(pd.Series(d), pd.Series(np.zeros(T)), pd.Series(dates), h)
    lags = max(h - 1, math.floor(4 * (T / 100) ** (2 / 9)))
    assert res.lags == lags
    ols = sm.OLS(d, np.ones(T)).fit(cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": False})
    hln = math.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    expected = float(ols.params[0] / ols.bse[0]) * hln
    assert res.stat == pytest.approx(expected, rel=1e-9)
    assert res.p_value_b_better == pytest.approx(float(stats.t.sf(expected, T - 1)), rel=1e-9)
    assert res.p_value_two_sided == pytest.approx(float(2 * stats.t.sf(abs(expected), T - 1)), rel=1e-9)
    assert res.mean_diff == pytest.approx(d.mean())


def test_diebold_mariano_averages_markets_within_a_month_first():
    """Many markets in one month are one observation, not many: T is the number of months."""
    rng = np.random.default_rng(5)
    months = pd.date_range("2021-01-01", periods=30, freq="MS")
    common = rng.normal(size=30)  # a shock shared by every market in the month
    rows = [(m, c + rng.normal(scale=0.1)) for m, c in zip(months, common, strict=True) for _ in range(50)]
    df = pd.DataFrame(rows, columns=["date", "d"])
    res = diebold_mariano(df["d"], pd.Series(np.zeros(len(df))), df["date"], 1)
    assert res.n_periods == 30
    monthly = df.groupby("date")["d"].mean().to_numpy()
    one = diebold_mariano(pd.Series(monthly), pd.Series(np.zeros(30)), pd.Series(months), 1)
    assert res.stat == pytest.approx(one.stat)


def test_diebold_mariano_has_roughly_nominal_size_under_serial_dependence():
    """Under H0 with AR(1) differentials the two-sided 5% test should reject near 5% of the time."""
    rng = np.random.default_rng(2024)
    dates = pd.Series(pd.date_range("2015-01-01", periods=70, freq="MS"))
    zeros = pd.Series(np.zeros(70))
    rejections = sum(
        diebold_mariano(pd.Series(_ar1(70, 0.3, rng)), zeros, dates, 3).p_value_two_sided < 0.05 for _ in range(600)
    )
    assert 0.02 <= rejections / 600 <= 0.10


def test_holm_by_hand_and_against_statsmodels():
    p = [0.01, 0.04, 0.03, 0.005]
    # sorted .005,.01,.03,.04 -> x4,x3,x2,x1 = .02,.03,.06,.04 -> running max .02,.03,.06,.06
    assert holm_adjust(p) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    rng = np.random.default_rng(1)
    q = rng.uniform(0, 0.2, 16).tolist()
    assert holm_adjust(q) == pytest.approx(multipletests(q, method="holm")[1].tolist())
    assert holm_adjust([0.01, None, 0.02]) == pytest.approx([0.02, None, 0.02], nan_ok=True) or holm_adjust(
        [0.01, None, 0.02]
    ) == [0.02, None, 0.02]
    assert holm_adjust([]) == []


def test_bootstrap_estimands_month_weighted_vs_row_weighted():
    # month 1: 1 market, losses a=1, b=3.  months 2..13: 3 markets each, a=1, b=1.
    dates, la, lb = [pd.Timestamp("2021-01-01")], [1.0], [3.0]
    for m in pd.date_range("2021-02-01", periods=12, freq="MS"):
        dates += [m] * 3
        la += [1.0] * 3
        lb += [1.0] * 3
    a, b, d = pd.Series(la), pd.Series(lb), pd.Series(dates)
    months = moving_block_bootstrap_ratio(a, b, d, 1, reps=200, seed=1, weighting="months")
    rows = moving_block_bootstrap_ratio(a, b, d, 1, reps=200, seed=1, weighting="rows")
    assert months["ratio"] == pytest.approx((3 + 12) / 13)  # mean of monthly means
    assert rows["ratio"] == pytest.approx((3 + 36) / 37)  # ratio of row sums
    assert months["ci_low"] <= months["ratio"] <= months["ci_high"]
    again = moving_block_bootstrap_ratio(a, b, d, 1, reps=200, seed=1, weighting="months")
    assert again == months  # deterministic for a fixed seed


def test_bootstrap_interval_covers_a_known_ratio():
    rng = np.random.default_rng(7)
    months = pd.date_range("2018-01-01", periods=72, freq="MS")
    d = pd.Series(np.repeat(months, 20))
    la = pd.Series(rng.gamma(2.0, 1.0, len(d)))
    lb = la * 0.8  # B's loss is exactly 80% of A's in every row
    out = moving_block_bootstrap_ratio(la, lb, d, 3, reps=300, seed=3)
    assert out["ratio"] == pytest.approx(0.8)
    assert out["ci_low"] == pytest.approx(0.8) and out["ci_high"] == pytest.approx(0.8)


def test_regression_metrics_by_hand():
    y = np.array([0.10, -0.20, 0.05])
    p = np.array([0.00, 0.00, 0.10])
    m = regression_metrics(y, p)
    assert m["mae"] == pytest.approx((0.10 + 0.20 + 0.05) / 3)
    assert m["rmse"] == pytest.approx(math.sqrt((0.01 + 0.04 + 0.0025) / 3))
    assert m["bias"] == pytest.approx((-0.10 + 0.20 + 0.05) / 3)


def test_brier_score_and_skill_by_hand():
    y = np.array([1, 0, 0, 1] * 5, dtype=float)
    p = np.array([0.8, 0.1, 0.3, 0.6] * 5)
    brier = (0.04 + 0.01 + 0.09 + 0.16) / 4
    base = 0.25  # forecasting the 50% base rate every time
    m = classification_metrics(y, p, 0.5, base_rate_brier=base, min_events=5)
    assert m["brier"] == pytest.approx(brier)
    assert m["brier_skill"] == pytest.approx(1 - brier / base)
    assert m["confusion"] == {"tp": 10, "fp": 0, "fn": 0, "tn": 10}


def test_common_sample_keeps_only_rows_every_model_predicted():
    rows = []
    for o in pd.date_range("2021-01-01", periods=4, freq="MS"):
        rows.append({"series_id": "s", "origin": o, "model": "a", "pred": 0.1, "y": 0.0})
        rows.append({"series_id": "s", "origin": o, "model": "b", "pred": np.nan if o.month == 2 else 0.2, "y": 0.0})
    cs = common_sample(pd.DataFrame(rows), ["a", "b"])
    assert sorted(cs["origin"].dt.month.unique()) == [1, 3, 4]
    assert (cs.groupby("origin")["model"].nunique() == 2).all()
