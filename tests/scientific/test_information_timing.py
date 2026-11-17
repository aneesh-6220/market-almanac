"""Information-time restrictions: what a forecast at origin t may use under each lag scenario."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shocktrace.evaluation.backtest import BacktestConfig, run_backtest
from shocktrace.experiments.config import ExperimentConfig
from shocktrace.experiments.runner import run_experiment, select_series
from shocktrace.features.builder import PRICE_FEATURES, _price_features, build_panel, family_features
from shocktrace.features.weather import WEATHER_FEATURES
from shocktrace.forecasting.models import default_specs
from shocktrace.forecasting.targets import log_change_target, spike_target


def _series(n: int = 60, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="MS")
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.05, n))), index=idx)


@pytest.mark.parametrize("lag", [0, 1, 2])
def test_target_is_change_from_last_published_price(lag):
    p = _series()
    t = pd.Timestamp("2018-06-01")
    for h in (1, 3):
        ref = p[t - pd.DateOffset(months=lag)]
        fut = p[t + pd.DateOffset(months=h)]
        assert log_change_target(p, h, lag)[t] == pytest.approx(np.log(fut) - np.log(ref))
        assert spike_target(p, h, 0.10, lag)[t] == float(fut / ref - 1 >= 0.10)


def test_hand_computed_lagged_target():
    # P: Jan 100, Feb 110, Mar 121, Apr 133.1.  Origin Mar, h=1, L=1: ln(133.1) - ln(110) = 2 ln(1.1)
    p = pd.Series([100.0, 110.0, 121.0, 133.1], index=pd.date_range("2020-01-01", periods=4, freq="MS"))
    y = log_change_target(p, 1, 1)
    assert y[pd.Timestamp("2020-03-01")] == pytest.approx(2 * np.log(1.1))
    assert np.isnan(y[pd.Timestamp("2020-01-01")])  # no price before January to anchor on
    assert spike_target(p, 1, 0.20, 1)[pd.Timestamp("2020-03-01")] == 1.0  # +21% over two months


@pytest.mark.parametrize("lag", [1, 2])
def test_price_features_never_use_unpublished_prices(lag):
    """Changing every price after t - L must leave all features at origins <= t untouched."""
    p = _series(72)
    cut = pd.Timestamp("2019-06-01")
    q = p.copy()
    q[q.index > cut - pd.DateOffset(months=lag)] *= 9.0
    cols = [*PRICE_FEATURES, "price", "log_price", "seasonal_naive_h1", "seasonal_naive_h3", "p_seas_hist_h1"]
    a = _price_features(p, (1, 3), (0.10,), lag).loc[:cut, cols]
    b = _price_features(q, (1, 3), (0.10,), lag).loc[:cut, cols]
    pd.testing.assert_frame_equal(a, b)
    # ... whereas with lag 0 the origin-month price is (by assumption) part of the information set
    a0 = _price_features(p, (1,), (0.10,), 0).loc[cut, "log_price"]
    b0 = _price_features(q, (1,), (0.10,), 0).loc[cut, "log_price"]
    assert a0 != b0


def test_reference_price_and_seasonal_naive_under_lag_by_hand():
    p = _series(48)
    lag, h = 2, 3
    f = _price_features(p, (h,), (0.10,), lag)
    t = pd.Timestamp("2018-03-01")
    off = lambda m: t + pd.DateOffset(months=m)  # noqa: E731
    assert f.loc[t, "price"] == pytest.approx(p[off(-lag)])
    assert f.loc[t, "price_ref_period"] == off(-lag)
    # same-span change one year earlier: ln P_{t+h-12} - ln P_{t-L-12}; both months are <= t - L
    assert off(h - 12) <= off(-lag)
    assert f.loc[t, f"seasonal_naive_h{h}"] == pytest.approx(np.log(p[off(h - 12)]) - np.log(p[off(-lag - 12)]))
    assert f.loc[t, f"y_dlog_h{h}"] == pytest.approx(np.log(p[off(h)]) - np.log(p[off(-lag)]))
    # the frame extends L months past the last observation: those origins still have a reference price
    assert f.index.max() == p.index.max() + pd.DateOffset(months=lag)
    assert f["price"].iloc[-1] == pytest.approx(p.iloc[-1])


def test_horizon_plus_lag_is_bounded():
    with pytest.raises(ValueError):
        _price_features(_series(), (11,), (0.10,), 2)
    with pytest.raises(ValueError):
        ExperimentConfig(name="t", country_iso3="XDM", commodity_codes=["X"], horizons=[11], price_release_lag_months=2)


@pytest.fixture(scope="module")
def ids(demo_data):  # type: ignore[no-untyped-def]
    cfg = ExperimentConfig(name="t", country_iso3="XDM", commodity_codes=["DM-MAIZE"])
    return select_series(demo_data, cfg)[0]


def test_panel_features_respect_price_and_weather_lags(demo_data, ids):
    cut = pd.Timestamp("2019-06-01")
    lag_p, lag_w = 1, 1
    base = build_panel(demo_data, ids, (1, 3), (0.10,), price_release_lag=lag_p, weather_release_lag=lag_w)
    future = {k: v.copy() for k, v in demo_data.items()}
    pr = future["prices"]
    pr.loc[pr["period"] > cut - pd.DateOffset(months=lag_p), "price"] *= 5.0
    wx = future["weather_monthly"]
    late = wx["period"] > cut - pd.DateOffset(months=lag_w)
    wx.loc[late, "precip_total_mm"] = 0.0
    wx.loc[late, "t2m_mean_c"] += 8
    wx.loc[late, "t2m_max_mean_c"] += 8
    alt = build_panel(future, ids, (1, 3), (0.10,), price_release_lag=lag_p, weather_release_lag=lag_w)
    feats = sorted(set(family_features("B", 1)) | set(family_features("B", 3)))
    a = base.panel[base.panel["origin"] <= cut].set_index(["series_id", "origin"])[feats]
    b = alt.panel[alt.panel["origin"] <= cut].set_index(["series_id", "origin"])[feats]
    pd.testing.assert_frame_equal(a, b)


def test_weather_lag_is_a_pure_shift(demo_data, ids):
    p0 = build_panel(demo_data, ids[:2], (1,), (0.10,)).panel.set_index(["series_id", "origin"])
    p1 = build_panel(demo_data, ids[:2], (1,), (0.10,), weather_release_lag=1).panel.set_index(["series_id", "origin"])
    sid = ids[0]
    t = pd.Timestamp("2018-09-01")
    for c in WEATHER_FEATURES:
        assert p1.loc[(sid, t), c] == pytest.approx(p0.loc[(sid, t - pd.DateOffset(months=1)), c], nan_ok=True)


@pytest.mark.parametrize("lag", [0, 1, 2])
def test_training_targets_are_published_before_each_refit(demo_data, ids, lag):
    fb = build_panel(demo_data, ids, (1, 3), (0.10,), price_release_lag=lag)
    specs = [s for s in default_specs(("A",), include_trees=False) if s.task == "regression"]
    for h in (1, 3):
        bt = run_backtest(
            fb.panel, specs, BacktestConfig(h=h, target=f"y_dlog_h{h}", task="regression", price_release_lag=lag)
        )
        p = bt.predictions
        published = p["train_last_origin"] + pd.DateOffset(months=h + lag)
        assert (published <= p["refit_date"]).all()
        assert (p["origin"] >= p["refit_date"]).all()


def test_forecast_states_origin_reference_price_and_target(demo_data):
    cfg = ExperimentConfig(
        name="t",
        country_iso3="XDM",
        commodity_codes=["DM-MAIZE"],
        horizons=[1],
        families=["A", "B"],
        include_trees=False,
        bootstrap_reps=100,
        sensitivity_thresholds=[0.10],
        price_release_lag_months=1,
    )
    out = run_experiment(demo_data, cfg, mode="demo", synthetic=True)
    last_price = demo_data["prices"]["period"].max()
    fc = [f for f in out.results["forecasts"] if f["task"] == "regression"]
    assert fc
    for f in fc:
        origin = pd.Timestamp(f["origin_period"])
        assert pd.Timestamp(f["last_price_period"]) == origin - pd.DateOffset(months=1)
        assert pd.Timestamp(f["last_price_period"]) <= last_price
        assert pd.Timestamp(f["target_period"]) == origin + pd.DateOffset(months=1)
        assert f["price_release_lag_months"] == 1
    man = out.results["manifest"]
    assert man["timing"]["price_release_lag_months"] == 1 and man["timing"]["verified_point_in_time"] is False
    assert any("t-1" in s and "ASSUMED" in s for s in out.results["limitations"])


def test_config_hash_is_stable_for_v01_configurations():
    """Fields added after v0.1.0 must not change the hash of a configuration that leaves them at default."""
    cfg = ExperimentConfig(name="Burkina Faso: Beans (niebe)", country_iso3="BFA", commodity_codes=["120"])
    assert cfg.config_hash() == "86211d13b414"  # recorded in the v0.1.0 cowpeas manifests
    assert cfg.model_copy(update={"price_release_lag_months": 1}).config_hash() != cfg.config_hash()
