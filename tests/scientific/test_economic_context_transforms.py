"""Economic transformations against hand-computed values: every definition is independently checkable."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from market_almanac.context import transforms as T


def monthly(values: list[float | None], start: str = "2020-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="MS")
    return pd.Series([np.nan if v is None else v for v in values], index=idx, dtype=float)


# --- month-over-month versus year-over-year ---------------------------------------------------------------------


def test_mom_and_yoy_are_different_horizons_of_the_same_level_series():
    s = monthly([100.0 * 1.01**i for i in range(24)])  # +1% every month
    mom, yoy = T.mom_pct(s), T.yoy_pct(s)
    assert mom.iloc[5] == pytest.approx(0.01)
    assert yoy.iloc[12] == pytest.approx(1.01**12 - 1)  # 12.68%, not 12%
    assert yoy.iloc[:12].isna().all() and math.isnan(mom.iloc[0])


def test_yoy_is_not_the_sum_of_monthly_changes():
    s = monthly([100.0 * 1.01**i for i in range(13)])
    assert T.yoy_pct(s).iloc[12] != pytest.approx(12 * 0.01)


def test_a_missing_month_gives_no_change_and_never_shifts_across_the_gap():
    s = monthly([100, 101, None, 103, 104, 105])
    mom = T.mom_pct(s)
    assert math.isnan(mom.iloc[2]) and math.isnan(mom.iloc[3])  # neither side of the hole has a one-month change
    assert mom.iloc[4] == pytest.approx(104 / 103 - 1)
    # the months absent from the index are the same as NaN months
    s2 = s.dropna()
    pd.testing.assert_series_equal(T.mom_pct(s2).dropna(), mom.dropna(), check_freq=False)


def test_yoy_needs_both_end_points_observed():
    vals: list[float | None] = [100.0 + i for i in range(14)]
    vals[1] = None  # the base month of month index 13
    yoy = T.yoy_pct(monthly(vals))
    assert math.isnan(yoy.iloc[13]) and yoy.iloc[12] == pytest.approx(112 / 100 - 1)


def test_duplicate_months_are_rejected_not_averaged():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-01", "2020-01-15"]))
    with pytest.raises(T.TransformError):
        T.as_monthly(s)


# --- index base changes -----------------------------------------------------------------------------------------


def test_changes_do_not_depend_on_the_index_base():
    s = monthly([100 + 2 * i for i in range(30)])
    scaled = s * 3.7  # same series on another base
    pd.testing.assert_series_equal(T.yoy_pct(s), T.yoy_pct(scaled))
    r1 = T.rebase(s, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-01"))
    r2 = T.rebase(scaled, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-01"))
    assert r1 is not None and r2 is not None
    pd.testing.assert_series_equal(r1, r2)
    assert r1[(r1.index >= "2020-01-01") & (r1.index <= "2020-12-01")].mean() == pytest.approx(100)


def test_unspliced_rebase_is_a_break_and_changes_across_it_are_withheld():
    # Level 100..., then the statistics office rebases and the level drops to 33 (as Libya's did) without splicing.
    levels = monthly([100 + i for i in range(14)] + [33 + 0.3 * i for i in range(14)])
    refs = pd.Series(["2008A"] * 14 + ["2024A"] * 14, index=levels.index)
    breaks = T.find_base_breaks(levels, refs)
    assert breaks == [pd.Timestamp("2021-03-01")]
    naive = T.mom_pct(levels)
    safe = T.mom_pct(levels, breaks)
    assert naive.loc["2021-03-01"] < -0.6  # the artefact: a 67% "deflation"
    assert math.isnan(safe.loc["2021-03-01"])
    yoy = T.yoy_pct(levels, breaks)
    # every 12-month change whose window spans the junction is withheld, then they resume
    assert yoy.loc["2021-03-01":"2022-02-01"].isna().all()
    assert not math.isnan(yoy.loc["2022-03-01"])


def test_a_spliced_rebase_is_not_a_break():
    levels = monthly([100 * 1.004**i for i in range(28)])
    refs = pd.Series(["2010A"] * 14 + ["2023A"] * 14, index=levels.index)
    assert T.find_base_breaks(levels, refs) == []


def test_a_large_jump_without_a_reference_period_change_is_not_called_a_break():
    levels = monthly([100, 101, 102, 200, 205])  # hyperinflation-like step, same base
    refs = pd.Series(["2010A"] * 5, index=levels.index)
    assert T.find_base_breaks(levels, refs) == []


def test_change_between_withholds_across_a_break():
    levels = monthly([100, 110, 120, 40, 44])
    b = [pd.Timestamp("2020-04-01")]
    assert T.change_between(levels, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-01"), b) == pytest.approx(0.2)
    assert T.change_between(levels, pd.Timestamp("2020-03-01"), pd.Timestamp("2020-05-01"), b) is None
    assert T.change_between(levels, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-05-01"), b) == pytest.approx(0.1)


# --- exchange-rate quote direction ------------------------------------------------------------------------------


def test_inverting_the_quote_inverts_the_value_and_changes_are_not_symmetric():
    local_per_usd = monthly([600.0, 750.0])  # +25% units per dollar
    usd_per_local = T.invert_quote(local_per_usd)
    assert usd_per_local.iloc[0] == pytest.approx(1 / 600)
    assert T.mom_pct(local_per_usd).iloc[1] == pytest.approx(0.25)
    assert T.mom_pct(usd_per_local).iloc[1] == pytest.approx(-0.20)
    assert T.usd_value_change(0.25) == pytest.approx(-0.20)
    assert T.usd_value_change(-0.5) == pytest.approx(1.0)  # halving the units per dollar doubles the dollar value


def test_invalid_exchange_rates_do_not_produce_values():
    assert T.invert_quote(monthly([0.0, -5.0, 2.0])).isna().tolist() == [True, True, False]
    with pytest.raises(T.TransformError):
        T.usd_value_change(-1.0)


def test_step_changes_are_reported_not_smoothed():
    fx = monthly([1500.0] * 6 + [15000.0] + [15000.0] * 3)
    steps = T.fx_step_changes(fx)
    assert [s["period"] for s in steps] == ["2020-07"] and steps[0]["mom_pct"] == pytest.approx(9.0)


# --- nominal, real and relative changes --------------------------------------------------------------------------


def test_a_53_percent_price_rise_is_not_53_percent_inflation():
    # rice +53%; consumer prices +12%: relative to the CPI the rice price rose 36.6%, not 41%
    assert T.real_change(0.53, 0.12) == pytest.approx(1.53 / 1.12 - 1)
    assert T.real_change(0.53, 0.12) != pytest.approx(0.53 - 0.12)
    assert T.real_change(0.10, 0.10) == pytest.approx(0.0)
    assert T.real_change(0.0, 1.0) == pytest.approx(-0.5)  # prices double elsewhere, this one stood still
    with pytest.raises(T.TransformError):
        T.real_change(0.1, -1.0)


def test_log_share_is_arithmetic_on_two_changes_and_withheld_when_the_whole_is_tiny():
    assert T.log_share(0.12, 0.53) == pytest.approx(math.log(1.12) / math.log(1.53))
    assert T.log_share(0.10, 0.005) is None  # a ratio of two near-zero changes means nothing
    assert T.log_share(-1.0, 0.5) is None


def test_benchmark_decomposition_is_an_exact_identity():
    d = T.decompose_log_change(usd_change=0.10, fx_change=0.20)
    assert d["local_currency_change"] == pytest.approx(1.10 * 1.20 - 1)
    assert d["usd_benchmark_log"] + d["exchange_rate_log"] == pytest.approx(d["local_currency_log"])


def test_usd_price_uses_the_rate_of_the_same_month_only():
    price = monthly([600.0, 700.0, 800.0])
    fx = monthly([600.0, None, 800.0])
    usd = T.to_usd(price, fx)
    assert usd.iloc[0] == pytest.approx(1.0) and math.isnan(usd.iloc[1]) and usd.iloc[2] == pytest.approx(1.0)


# --- lagged comparison --------------------------------------------------------------------------------------------


def test_lagged_comparison_recovers_a_built_in_lead_and_reports_every_lag():
    rng = np.random.default_rng(7)
    ref_levels = monthly(list(100 * np.exp(np.cumsum(rng.normal(0, 0.04, 80)))))
    ref_ch = T.log_monthly_changes(ref_levels)
    # the local price follows the reference with a 3-month delay, plus a little noise
    local_ch = ref_ch.shift(3, freq="MS") + pd.Series(rng.normal(0, 0.002, len(ref_ch)), index=ref_ch.index)
    rows = T.lagged_comparison(local_ch.dropna(), ref_ch.dropna())
    assert [r.lag for r in rows] == list(range(7))  # all lags returned, not only the best
    by = {r.lag: r for r in rows}
    assert by[3].spearman is not None and by[3].spearman > 0.9
    assert all(abs(by[k].spearman or 0) < 0.5 for k in (0, 1, 5, 6))
    assert all(r.n >= 24 for r in rows)


def test_lagged_comparison_withholds_short_samples_instead_of_reporting_zero():
    a = monthly([1.0, 2.0, 1.5, 3.0, 2.5] * 3)
    b = monthly([2.0, 1.0, 2.5, 1.0, 3.0] * 3)
    rows = T.lagged_comparison(a, b)
    assert all(r.status == "insufficient" and r.spearman is None for r in rows)


def test_lagged_comparison_refuses_negative_lags():
    s = monthly(list(range(40)))
    with pytest.raises(T.TransformError):
        T.lagged_comparison(s, s, lags=(-1,))


# --- information availability ---------------------------------------------------------------------------------------


def test_release_lag_removes_observations_not_yet_published_as_of_a_date():
    s = monthly(list(range(1, 25)))  # Jan 2020 .. Dec 2021
    asof = pd.Timestamp("2021-06-15")
    kept = T.available_as_of(s, release_lag_months=2, as_of=asof)
    assert kept.index.max() == pd.Timestamp("2021-04-01")  # April is the latest month assumed published by June
    assert T.available_as_of(s, 0, asof).index.max() == pd.Timestamp("2021-06-01")
    assert len(T.available_as_of(s, 2, None)) == 24  # exploratory mode keeps the full archived vintage
