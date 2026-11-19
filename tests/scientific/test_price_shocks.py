"""Scientific correctness of price-shock detection, episodes, comparisons and evidence (synthetic, offline)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_almanac.analytics.shocks import (
    MIN_REFERENCE,
    Z_ELEVATED,
    clean_monthly,
    compute_signals,
    episode_at,
    extent,
    find_episodes,
    seasonal_expectation,
    state_near,
)


def series(
    n: int = 120,
    start: str = "2012-01-01",
    seed: int = 0,
    level: float = 100.0,
    noise: float = 0.03,
    seasonal: float = 0.0,
    trend: float = 0.0,
) -> pd.Series:
    """Log-random-walk-free monthly prices: level x exp(trend t + seasonal sin + iid noise)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="MS")
    t = np.arange(n)
    lp = (
        np.log(level)
        + trend * t
        + seasonal * np.sin(2 * np.pi * (idx.month.to_numpy() - 1) / 12)
        + rng.normal(0, noise, n)
    )
    return pd.Series(np.exp(lp), index=idx)


def shock(p: pd.Series, at: str, months: int, factor: float) -> pd.Series:
    q = p.copy()
    i = q.index.get_loc(pd.Timestamp(at))
    q.iloc[i : i + months] *= factor
    return q


# --- signals --------------------------------------------------------------------------------------------


def test_no_assessment_on_sparse_or_short_series():
    sig = compute_signals(series(30))
    assert set(sig["status"]) <= {"none", "withheld"}
    assert set(sig.loc[sig["status"] == "withheld", "reason"]) == {"short_history"}
    assert sig["z"].isna().all()
    # a long series with most recent months missing: withheld as sparse, not scored
    p = series(120)
    recent = p.index[-24:-1]
    sparse = p.drop([t for i, t in enumerate(recent) if i % 3])  # two of every three recent months missing
    s2 = compute_signals(sparse)
    last = s2[s2["r12"].notna()].iloc[-1]
    assert last["status"] == "withheld" and last["reason"] == "sparse_recent"


def test_missing_months_are_not_zero_changes_and_never_bridged():
    p = series(100).drop(pd.Timestamp("2016-06-01"))
    sig = compute_signals(p)
    assert not sig.at[pd.Timestamp("2016-06-01"), "observed"]
    assert np.isnan(sig.at[pd.Timestamp("2016-06-01"), "r1"]) and np.isnan(sig.at[pd.Timestamp("2016-07-01"), "r1"])
    assert np.isnan(sig.at[pd.Timestamp("2017-06-01"), "r12"])  # its comparison month is missing


def test_zero_negative_and_invalid_prices_are_dropped_before_any_ratio():
    p = series(80)
    p.iloc[40] = 0.0
    p.iloc[41] = -5.0
    p.iloc[42] = np.nan
    p.iloc[43] = np.inf
    c = clean_monthly(p)
    assert len(c) == 76 and (c > 0).all() and np.isfinite(c).all()
    sig = compute_signals(p)
    assert np.isfinite(sig["r12"].dropna()).all()
    assert not sig["observed"].iloc[40:44].any()


def test_duplicate_month_keeps_first_and_index_is_monthly():
    p = series(40)
    dup = pd.concat([p, pd.Series([999.0], index=[p.index[10] + pd.Timedelta(days=14)])])
    c = clean_monthly(dup)
    assert c.index.is_unique and c.loc[p.index[10]] == pytest.approx(p.iloc[10])


def test_no_leakage_future_data_cannot_change_a_past_assessment():
    p = series(150, seed=3)
    base = compute_signals(p.iloc[:110])
    full = compute_signals(shock(p, p.index[120].isoformat(), 20, 3.0))
    t = p.index[105]
    for c in ("z", "percentile", "n_reference"):
        assert base.at[t, c] == pytest.approx(full.at[t, c], nan_ok=True)


def test_degenerate_constant_history_is_withheld_not_scored():
    idx = pd.date_range("2010-01-01", periods=96, freq="MS")
    p = pd.Series(100.0, index=idx)
    p.iloc[-1] = 400.0  # a x4 jump after years of carried-forward prices
    sig = compute_signals(p)
    assert sig.iloc[-1]["status"] == "withheld" and sig.iloc[-1]["reason"] == "degenerate_history"
    assert not [e for e in find_episodes(sig) if e["kind"] == "unusual"]
    assert [e for e in find_episodes(sig) if e["kind"] == "withheld"]


def test_eligibility_needs_enough_years_and_reference_changes():
    sig = compute_signals(series(12 + MIN_REFERENCE + 24))
    ok = sig[sig["status"] == "ok"]
    assert len(ok) >= 1 and (ok["n_reference"] >= MIN_REFERENCE).all() and (ok["reference_years"] >= 4).all()


# --- episodes -------------------------------------------------------------------------------------------


def test_a_genuine_sustained_shock_is_one_persistent_unusual_episode():
    p = shock(series(132, seed=1), "2019-03-01", 9, 1.6)
    eps = [e for e in find_episodes(compute_signals(p)) if e["kind"] == "unusual" and e["direction"] == "up"]
    around = [e for e in eps if "2018-09-01" <= e["start"] <= "2019-12-01"]
    assert len(around) == 1  # one episode, not fragments (earlier single noisy months may also qualify)
    e = around[0]
    assert e["start"] == "2019-03-01" and e["duration_months"] >= 8
    assert e["peak_z"] >= Z_ELEVATED and e["peak_percentile"] == 1.0
    assert e["peak_yoy_pct"] == pytest.approx(0.6, abs=0.15)
    assert not e["data_concern"] and e["peak_index"] > 140
    assert e["baseline"]["n"] == 12


def test_a_corrupted_single_month_spike_is_flagged_as_a_data_concern():
    p = series(132, seed=2)
    p.iloc[90] *= 10  # x10 for one month (unit or keying error), then back
    eps = find_episodes(compute_signals(p))
    up = [e for e in eps if e["kind"] == "unusual" and e["direction"] == "up"]
    assert len(up) == 1 and up[0]["duration_months"] == 1
    assert {"implausible_jump", "single_month_reversed"} <= set(up[0]["flags"]) and up[0]["data_concern"]
    # twelve months later the spike becomes the comparison month: a mirrored fall flagged as a base effect
    down = [e for e in eps if e["direction"] == "down" and e["kind"] == "unusual"]
    assert down and "possible_base_effect" in down[0]["flags"]


def test_regular_seasonality_alone_is_not_unusual():
    p = series(144, seed=4, seasonal=0.25, noise=0.02)
    eps = [e for e in find_episodes(compute_signals(p)) if e["kind"] == "unusual"]
    assert not eps  # +/-25% seasonal swings every year: 12-month changes stay ordinary


def test_seasonal_expectation_separates_a_seasonal_rise_from_a_shock():
    p = series(144, seed=5, seasonal=0.25, noise=0.01)
    sig = compute_signals(p)
    # a rise from the trough (Oct) to the peak (Apr) is what the pattern predicts
    se = seasonal_expectation(sig, pd.Timestamp("2021-01-01"), pd.Timestamp("2021-04-01"))
    assert se["status"] == "ok" and se["verdict"] == "largely_seasonal"
    shocked = shock(p, "2021-01-01", 4, 1.8)
    se2 = seasonal_expectation(compute_signals(shocked), pd.Timestamp("2021-01-01"), pd.Timestamp("2021-04-01"))
    assert (
        se2["verdict"] in ("partly_seasonal", "not_seasonal") and se2["observed_change_pct"] > se["observed_change_pct"]
    )


def test_large_nominal_change_typical_under_inflation_is_not_unusual():
    p = series(132, seed=6, trend=np.log(1.04), noise=0.02)  # ~60% a year, every year
    eps = find_episodes(compute_signals(p))
    assert not [e for e in eps if e["kind"] == "unusual" and e["direction"] == "up"]
    typical = [e for e in eps if e["kind"] == "large_typical" and e["direction"] == "up"]
    assert typical and typical[0]["peak_yoy_pct"] > 0.25


def test_episode_lookup_prefers_unusual():
    p = shock(series(132, seed=1), "2019-03-01", 9, 1.6)
    eps = find_episodes(compute_signals(p))
    assert episode_at(eps, pd.Timestamp("2019-06-01"))["kind"] == "unusual"
    assert episode_at(eps, pd.Timestamp("2014-01-01")) is None


# --- extent ---------------------------------------------------------------------------------------------


def _panel(n_peers: int, shocked: int, seed: int = 10) -> dict[str, pd.Series]:
    out = {}
    for i in range(n_peers):
        p = series(132, seed=seed + i)
        out[f"s{i}"] = shock(p, "2019-03-01", 6, 1.7) if i < shocked else p
    return out


@pytest.mark.parametrize(("shocked", "expected"), [(9, "widespread"), (1, "local"), (4, "mixed")])
def test_local_versus_widespread(shocked, expected):
    panel = _panel(10, shocked)
    sigs = {k: compute_signals(v) for k, v in panel.items()}
    peak = pd.Timestamp("2019-05-01")
    states = [state_near(s, peak, "up") for k, s in sigs.items() if k != "s0"]
    assert extent(states)["class"] == expected


def test_extent_is_inconclusive_with_too_few_assessable_peers():
    panel = _panel(3, 3)
    sigs = {k: compute_signals(v.iloc[-40:]) for k, v in panel.items()}  # too short to assess
    states = [state_near(s, pd.Timestamp("2019-05-01"), "up") for s in sigs.values()]
    ex = extent(states)
    assert ex["class"] == "inconclusive" and ex["n_assessable"] == 0
