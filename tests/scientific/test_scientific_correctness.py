"""Explicit tests of the scientific-correctness requirements (numbered as in the specification)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_almanac.data.alignment import RULES, asof_align
from market_almanac.data.quality import assess_prices, clean_monthly_series
from market_almanac.evaluation.backtest import BacktestConfig, InsufficientDataError, run_backtest
from market_almanac.experiments.config import ExperimentConfig
from market_almanac.experiments.runner import overall_conclusion, qualify_forecast, run_experiment, select_series
from market_almanac.features.builder import build_panel, family_features
from market_almanac.features.weather import ClimatologyConfig, LeakageError, anomaly, check_fixed_climatology
from market_almanac.forecasting.models import FittedModel, default_specs
from market_almanac.forecasting.targets import log_change_target, spike_target
from market_almanac.providers.hdx_hapi import normalize_food_prices
from tests.conftest import fixture_json
from tests.unit.test_data_layer import _prices


@pytest.fixture(scope="module")
def maize(demo_data):  # type: ignore[no-untyped-def]
    cfg = ExperimentConfig(name="t", country_iso3="XDM", commodity_codes=["DM-MAIZE"])
    ids, _ = select_series(demo_data, cfg)
    return ids, build_panel(demo_data, ids, (1, 3), (0.10,))


# 1 ------------------------------------------------------------------------------------------
def test_1_features_at_t_never_use_later_observations(demo_data, maize):
    ids, fb = maize
    cut = pd.Timestamp("2019-06-01")
    future = {k: v.copy() for k, v in demo_data.items()}
    p = future["prices"]
    p.loc[p["period"] > cut, "price"] *= 7.0
    w = future["weather_monthly"]
    w.loc[w["period"] > cut, "precip_total_mm"] = 0.0
    w.loc[w["period"] > cut, "t2m_mean_c"] += 10
    m = future["macro"]
    m.loc[m["period"] > cut, "value"] *= 3
    fb2 = build_panel(future, ids, (1, 3), (0.10,))
    feats = sorted(set(family_features("D", 1)) | set(family_features("D", 3)))
    a = fb.panel[fb.panel["origin"] <= cut].set_index(["series_id", "origin"])[feats]
    b = fb2.panel[fb2.panel["origin"] <= cut].set_index(["series_id", "origin"])[feats]
    pd.testing.assert_frame_equal(a, b)
    # targets at t <= cut *do* change when they reach past the cut (they are outcomes, not features)
    ta = fb.panel.set_index(["series_id", "origin"]).loc[lambda d: d.index.get_level_values(1) == cut, "y_dlog_h1"]
    tb = fb2.panel.set_index(["series_id", "origin"]).loc[lambda d: d.index.get_level_values(1) == cut, "y_dlog_h1"]
    assert not np.allclose(ta.values, tb.values)


# 2 ------------------------------------------------------------------------------------------
def test_2_train_test_partitions_are_chronological(maize):
    _, fb = maize
    specs = [s for s in default_specs(("A",), include_trees=False) if s.task == "regression"]
    for h in (1, 3):
        bt = run_backtest(fb.panel, specs, BacktestConfig(h=h, target=f"y_dlog_h{h}", task="regression"))
        p = bt.predictions
        assert ((p["train_last_origin"] + pd.DateOffset(months=h)) <= p["refit_date"]).all()
        assert (p["origin"] >= p["refit_date"]).all()
        for f in bt.folds:
            assert pd.Timestamp(f["train_last_origin"]) < pd.Timestamp(f["test_first_origin"])


# 3 ------------------------------------------------------------------------------------------
def test_3_preprocessing_never_fits_on_held_out_data(maize):
    _, fb = maize
    panel = fb.panel[fb.panel["y_dlog_h1"].notna() & fb.panel["log_price"].notna()]
    cut = pd.Timestamp("2018-01-01")
    train = panel[panel["origin"] + pd.DateOffset(months=1) <= cut]
    spec = next(s for s in default_specs(("A", "B")) if s.name == "ridge_B")
    m1 = FittedModel(spec, 1).fit(train, "y_dlog_h1")
    scaler = m1.estimator.named_steps["scale"]
    imputer = m1.estimator.named_steps["impute"]
    X = train[m1.features]
    np.testing.assert_allclose(imputer.statistics_, X.median().values)
    np.testing.assert_allclose(scaler.mean_, X.fillna(X.median()).mean().values, rtol=1e-10)
    # altering held-out rows cannot change the fitted model
    held = panel[panel["origin"] >= cut].copy()
    held[m1.features] = held[m1.features] * 100 + 5
    m2 = FittedModel(spec, 1).fit(train, "y_dlog_h1")
    np.testing.assert_allclose(m1.predict(held), m2.predict(held))


# 4 ------------------------------------------------------------------------------------------
def test_4_seasonal_naive_uses_the_correct_historical_period():
    df = _prices(48)
    fb = build_panel({"prices": df}, list(df["series_id"].unique()), (1, 3), (0.10,))
    p = fb.panel.set_index("origin")
    lp = np.log(df.set_index("period")["price"])
    t = pd.Timestamp("2018-06-01")
    for h in (1, 3):
        expected = lp[t - pd.DateOffset(months=12 - h)] - lp[t - pd.DateOffset(months=12)]
        assert p.loc[t, f"seasonal_naive_h{h}"] == pytest.approx(expected)
    assert np.isnan(p.iloc[5]["seasonal_naive_h1"])  # needs a year of history


# 5 ------------------------------------------------------------------------------------------
def test_5_missing_future_outcomes_are_not_negative_events():
    price = pd.Series([100, 100, np.nan, 100, 150.0], index=pd.date_range("2020-01-01", periods=5, freq="MS"))
    s = spike_target(price, 1, 0.10)
    assert np.isnan(s.iloc[1]) and np.isnan(s.iloc[2])  # P_{t+1} or P_t missing
    assert s.iloc[0] == 0 and s.iloc[3] == 1 and np.isnan(s.iloc[4])  # last: no future
    y = log_change_target(price, 1)
    assert np.isnan(y.iloc[1]) and np.isnan(y.iloc[4])


# 6 ------------------------------------------------------------------------------------------
def test_6_incompatible_units_are_not_merged():
    raw = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"][:2]
    other = [{**r, "unit": "90 KG", "price": r["price"] * 90} for r in raw]
    df, _, _ = normalize_food_prices(raw + other, pd.Timestamp.now(tz="UTC"))
    by_unit = df.groupby("unit")["series_id"].nunique()
    assert set(by_unit.index) == {"KG", "90 KG"}
    assert df.groupby("series_id")["unit"].nunique().max() == 1
    monthly = clean_monthly_series(pd.concat([_prices(12, unit="KG"), _prices(12, unit="50 KG")]))
    assert monthly["series_id"].nunique() == 2
    q, _ = assess_prices(pd.concat([_prices(60, unit="KG"), _prices(60, unit="50 KG")]))
    assert len(q) == 2


# 7 ------------------------------------------------------------------------------------------
def test_7_unknown_release_dates_are_not_treated_as_known():
    vals = pd.DataFrame(
        {"period": pd.to_datetime(["2020-01-01", "2020-02-01"]), "value": [1.0, 2.0], "published_at": [pd.NaT, pd.NaT]}
    )
    origins = pd.Series(pd.to_datetime(["2020-02-01", "2020-03-01", "2020-04-01"]))
    out = asof_align(origins, vals, RULES["imf_cpi"])  # 2-month conservative lag
    assert np.isnan(out.iloc[0]) and out.iloc[1] == 1.0 and out.iloc[2] == 2.0
    known = vals.assign(published_at=pd.to_datetime(["2020-02-05", "2020-03-25"], utc=True))
    out2 = asof_align(origins, known, RULES["imf_cpi"])
    # genuine publication dates are honoured (earlier than the conservative lag would allow)
    assert out2.iloc[0] == 1.0 and out2.iloc[1] == 2.0
    # providers never back-fill publication dates from retrieval dates
    df, _, _ = normalize_food_prices(
        fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"], pd.Timestamp.now(tz="UTC")
    )
    assert df["published_at"].isna().all() and df["retrieved_at"].notna().all()


# 8 ------------------------------------------------------------------------------------------
def test_8_weather_anomalies_use_a_proper_historical_reference_window():
    idx = pd.date_range("1990-01-01", "2010-12-01", freq="MS")
    x = pd.Series(np.random.default_rng(3).normal(100, 10, len(idx)), index=idx)
    z = anomaly(x, ClimatologyConfig("expanding", min_years=10))
    t = pd.Timestamp("2005-07-01")
    prior = x[(x.index.month == 7) & (x.index < t)]
    assert z[t] == pytest.approx((x[t] - prior.mean()) / prior.std())
    assert np.isnan(z[pd.Timestamp("1995-07-01")])  # fewer than 10 prior years
    x2 = x.copy()
    x2[x2.index > t] += 500
    pd.testing.assert_series_equal(z[z.index <= t], anomaly(x2, ClimatologyConfig("expanding"))[z.index <= t])
    fixed = ClimatologyConfig("fixed", 1990, 2004)
    check_fixed_climatology(fixed, pd.Timestamp("2006-01-01"))
    with pytest.raises(LeakageError):
        check_fixed_climatology(ClimatologyConfig("fixed", 1991, 2020), pd.Timestamp("2016-01-01"))


# 9 ------------------------------------------------------------------------------------------
def test_9_forecast_errors_are_computed_against_the_correct_target(demo_data, maize):
    ids, fb = maize
    specs = [s for s in default_specs(("A",), include_trees=False) if s.name == "naive"]
    bt = run_backtest(fb.panel, specs, BacktestConfig(h=3, target="y_dlog_h3", task="regression"))
    p = bt.predictions.iloc[:50]
    monthly = clean_monthly_series(demo_data["prices"][demo_data["prices"]["series_id"].isin(ids)]).set_index(
        ["series_id", "period"]
    )["price"]
    for r in p.itertuples():
        expected = np.log(monthly[(r.series_id, r.target_period)]) - np.log(monthly[(r.series_id, r.origin)])
        assert r.y == pytest.approx(expected)
        assert r.target_period == r.origin + pd.DateOffset(months=3)
    assert (bt.predictions["pred"] == 0).all()


# 10 -----------------------------------------------------------------------------------------
def test_10_predictions_cannot_be_labelled_validated_without_evaluation():
    cfg = ExperimentConfig(name="t", country_iso3="XDM", commodity_codes=["X"])
    assert qualify_forecast(None, "ridge_B", cfg)[0] == "not_evaluated"
    assert qualify_forecast({"status": "ok", "models": {}}, "ridge_B", cfg)[0] == "not_evaluated"
    short = {"status": "ok", "models": {"ridge_B": {}}, "n_test_periods": 5, "comparisons": []}
    assert qualify_forecast(short, "ridge_B", cfg)[0] == "insufficient_validation"
    nocomp = {"status": "ok", "models": {"ridge_B": {}}, "n_test_periods": 60, "comparisons": []}
    assert qualify_forecast(nocomp, "ridge_B", cfg)[0] == "insufficient_validation"


# Additional guarantees ----------------------------------------------------------------------
def test_insufficient_history_is_refused():
    df = _prices(30)
    fb = build_panel({"prices": df}, list(df["series_id"].unique()), (1,), (0.10,))
    with pytest.raises(InsufficientDataError):
        run_backtest(fb.panel, default_specs(("A",)), BacktestConfig(h=1, target="y_dlog_h1", task="regression"))
    out = run_experiment(
        {"prices": df}, ExperimentConfig(name="s", country_iso3="KEN", commodity_codes=["1"]), mode="test"
    )
    assert out.results["status"] == "insufficient_evidence"
    assert out.results["conclusion"]["verdict"] == "insufficient_evidence"


def test_conclusion_logic_supports_negative_and_mixed_outcomes():
    def c(v: str) -> dict:
        return {
            "role": "primary",
            "verdict": v,
            "task": "regression",
            "horizon": 1,
            "model_a": "a",
            "model_b": "b",
            "reason": "",
            "relative_loss_b_vs_a": 1.0,
        }

    assert overall_conclusion([c("improved"), c("improved")])["verdict"] == "improved"
    assert overall_conclusion([c("not_improved"), c("not_improved")])["verdict"] == "not_improved"
    assert overall_conclusion([c("improved"), c("not_improved")])["verdict"] == "inconsistent"
    assert overall_conclusion([c("insufficient_evidence")])["verdict"] == "insufficient_evidence"
    assert overall_conclusion([c("insufficient_evidence"), c("not_improved")])["verdict"] == "not_improved"


def test_experiment_is_deterministic(demo_data):
    cfg = ExperimentConfig(
        name="d",
        country_iso3="XDM",
        commodity_codes=["DM-RICE"],
        horizons=[1],
        include_trees=False,
        families=["A", "B"],
        sensitivity_thresholds=[0.10],
        bootstrap_reps=200,
    )
    a = run_experiment(demo_data, cfg, mode="demo", synthetic=True, experiment_id="x")
    b = run_experiment(demo_data, cfg, mode="demo", synthetic=True, experiment_id="x")
    ta, tb = a.results["tasks"][0]["models"], b.results["tasks"][0]["models"]
    assert {k: v["mae"] for k, v in ta.items()} == {k: v["mae"] for k, v in tb.items()}
    assert a.results["conclusion"] == b.results["conclusion"]
    assert any("SYNTHETIC" in x for x in a.results["limitations"])


def test_models_without_overlapping_predictions_are_insufficient_not_a_crash():
    from market_almanac.evaluation.backtest import BacktestConfig, BacktestResult, common_sample
    from market_almanac.experiments.config import ExperimentConfig
    from market_almanac.experiments.runner import _task_block
    from market_almanac.forecasting.models import default_specs

    t = pd.date_range("2020-01-01", periods=30, freq="MS")
    rows = [
        {"series_id": "ps_a", "origin": o, "target_period": o, "model": m, "pred": 0.0, "y": 0.0, "fold": 0}
        for i, o in enumerate(t)
        for m in (["naive"] if i % 2 else ["ridge_A"])
    ]
    preds = pd.DataFrame(rows)
    assert common_sample(preds, ["naive", "ridge_A"]).empty
    assert common_sample(preds, ["naive", "ridge_B"]).empty  # ridge_B never predicted
    bt = BacktestResult(BacktestConfig(h=1, target="y_dlog_h1", task="regression"), preds, folds=[])
    cfg = ExperimentConfig(name="t", country_iso3="XDM", commodity_codes=["DM-MAIZE"])
    specs = [s for s in default_specs(("A",), include_trees=False) if s.task == "regression"]
    block, sample = _task_block(bt, pd.DataFrame(), specs, "regression", 1, cfg, None, [])
    assert block["status"] == "insufficient_evidence" and sample.empty and block["comparisons"] == []


# audit regressions (docs/audits/SCIENTIFIC_VALIDITY_AUDIT.md) -------------------------------
def test_anomaly_is_bounded_when_climatological_sd_is_near_zero():
    """Dry-season rainfall: near-zero s.d. plus one spurious value must not produce z ~ 200."""
    from market_almanac.features.weather import ANOMALY_CLIP

    idx = pd.date_range("1991-12-01", periods=35, freq="12MS")  # 35 Decembers
    x = pd.Series(np.r_[np.tile([0.0, 0.1, 0.0, 2.1, 0.0], 6), 0.0, 0.0, 0.0, 0.0, 291.3], index=idx)
    z = anomaly(x, ClimatologyConfig())
    assert z.iloc[-1] == ANOMALY_CLIP
    assert z.abs().max() <= ANOMALY_CLIP
    # ordinary values are untouched by the clip
    raw = (x.iloc[-2] - x.iloc[:-2].mean()) / x.iloc[:-2].std()
    assert z.iloc[-2] == pytest.approx(raw)


def test_anomaly_clip_does_not_reintroduce_future_information():
    idx = pd.date_range("1991-01-01", periods=12 * 30, freq="MS")
    rng = np.random.default_rng(0)
    x = pd.Series(rng.gamma(2.0, 30.0, len(idx)), index=idx)
    cut = pd.Timestamp("2015-06-01")
    x2 = x.copy()
    x2[x2.index > cut] = 1e6
    a, b = anomaly(x, ClimatologyConfig()), anomaly(x2, ClimatologyConfig())
    pd.testing.assert_series_equal(a[a.index <= cut], b[b.index <= cut])


def test_results_disclose_lag_assumption_timing(demo_data):
    from market_almanac.data.alignment import RULES
    from market_almanac.experiments.runner import TIMING_DISCLOSURE

    assert "ASSUMED" in RULES["price"].basis and "not a real-time" in RULES["price"].basis
    cfg = ExperimentConfig(
        name="t",
        country_iso3="XDM",
        commodity_codes=["DM-MAIZE"],
        horizons=[1],
        families=["A", "B"],
        include_trees=False,
        bootstrap_reps=100,
        sensitivity_thresholds=[0.10],
    )
    out = run_experiment(demo_data, cfg, mode="demo")
    assert TIMING_DISCLOSURE in out.results["limitations"]
    man = out.results["manifest"]
    assert "precip-qc-1" in man["method_revision"] and man["feature_transform_version"]
    assert man["timing"] == {
        "price_release_lag_months": 0,
        "weather_release_lag_months": 0,
        "statement": man["timing"]["statement"],
        "verified_point_in_time": False,
    }
