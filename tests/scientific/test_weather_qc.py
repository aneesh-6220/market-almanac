"""Daily precipitation quality control (precip-qc-1) and its effect on monthly aggregates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shocktrace.data.weather import aggregate_daily_to_monthly, flag_implausible_precipitation


def _daily(end: str = "2025-12-31", seed: int = 3) -> pd.DataFrame:
    """Sahel-like cell: rain only June-September, capped at 90 mm/day; dry season exactly zero."""
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"date": pd.date_range("1991-01-01", end, freq="D")})
    wet = d["date"].dt.month.isin([6, 7, 8, 9])
    rain = np.where(wet, np.minimum(rng.gamma(0.6, 12.0, len(d)), 90.0), 0.0)
    d["PRECTOTCORR"] = rain
    d["T2M"], d["T2M_MAX"], d["T2M_MIN"] = 28.0, 34.0, 22.0
    return d


def _set(d: pd.DataFrame, day: str, mm: float) -> None:
    d.loc[d["date"] == pd.Timestamp(day), "PRECTOTCORR"] = mm


def test_dry_season_artefact_is_flagged_and_raw_value_preserved():
    d = _daily()
    _set(d, "2025-12-02", 276.54)
    flags = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"])
    assert flags.sum() == 1 and d.loc[flags, "date"].iloc[0] == pd.Timestamp("2025-12-02")
    m = aggregate_daily_to_monthly(d).set_index("period").loc[pd.Timestamp("2025-12-01")]
    assert m["precip_qc_flagged_days"] == 1
    assert m["precip_qc_max_flagged_mm"] == pytest.approx(276.54)
    assert m["precip_total_mm_raw"] == pytest.approx(276.54)  # raw total keeps the source value
    assert m["precip_total_mm"] == pytest.approx(0.0)  # QC'd total treats the day as missing
    # without QC the old behaviour is reproduced exactly
    m0 = aggregate_daily_to_monthly(d, precip_qc=False).set_index("period").loc[pd.Timestamp("2025-12-01")]
    assert m0["precip_total_mm"] == pytest.approx(276.54) and m0["precip_qc_flagged_days"] == 0


def test_ordinary_wet_season_storm_is_not_flagged():
    d = _daily()
    prior_max = d.loc[d["date"].dt.month.isin([7, 8, 9]) & (d["date"].dt.year < 2025), "PRECTOTCORR"].max()
    assert 60 < prior_max <= 90
    _set(d, "2025-08-14", 120.0)  # a severe storm, but less than twice the cell's own seasonal record
    assert flag_implausible_precipitation(d["date"], d["PRECTOTCORR"]).sum() == 0
    _set(d, "2025-08-15", 2 * prior_max + 1)  # more than double the record: implausible even in August
    flags = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"])
    assert list(d.loc[flags, "date"]) == [pd.Timestamp("2025-08-15")]


def test_moderate_dry_season_rain_below_absolute_floor_is_kept():
    d = _daily()
    _set(d, "2025-12-02", 30.0)  # unusual for December, but physically ordinary: not flagged
    assert flag_implausible_precipitation(d["date"], d["PRECTOTCORR"]).sum() == 0


def test_no_flags_without_enough_reference_years():
    d = _daily()
    _set(d, "1995-12-02", 300.0)  # only four earlier years: no basis for calling it implausible
    flags = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"])
    assert not flags[(d["date"] == pd.Timestamp("1995-12-02")).to_numpy()].any()


def test_flagged_values_do_not_become_the_new_record():
    d = _daily()
    _set(d, "2024-12-05", 300.0)
    _set(d, "2025-12-02", 280.0)  # would pass if the 2024 artefact had raised the December record
    flags = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"])
    assert set(d.loc[flags, "date"]) == {pd.Timestamp("2024-12-05"), pd.Timestamp("2025-12-02")}


def test_flags_use_only_earlier_years():
    """A flag for a day never depends on data from the same or later years (real-time computable)."""
    d = _daily()
    _set(d, "2015-12-02", 250.0)
    a = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"])
    e = d.copy()
    later = e["date"] >= pd.Timestamp("2016-01-01")
    e.loc[later, "PRECTOTCORR"] = e.loc[later, "PRECTOTCORR"] * 40 + 500
    b = flag_implausible_precipitation(e["date"], e["PRECTOTCORR"])
    early = (d["date"] < pd.Timestamp("2016-01-01")).to_numpy()
    assert a[early].sum() == 1
    np.testing.assert_array_equal(a[early], b[early])


def test_month_with_too_many_flagged_days_has_no_qc_total():
    d = _daily()
    for day in ("02", "05", "09", "13"):  # 4 of 31 days flagged: fewer than 90% of days remain
        _set(d, f"2025-12-{day}", 200.0)
    m = aggregate_daily_to_monthly(d).set_index("period").loc[pd.Timestamp("2025-12-01")]
    assert m["precip_qc_flagged_days"] == 4
    assert np.isnan(m["precip_total_mm"]) and m["precip_total_mm_raw"] == pytest.approx(800.0)
    assert bool(m["complete"]) and m["t2m_mean_c"] == pytest.approx(28.0)  # temperature is unaffected


def test_qc_leaves_clean_history_identical():
    d = _daily()
    a = aggregate_daily_to_monthly(d)
    b = aggregate_daily_to_monthly(d, precip_qc=False)
    assert a["precip_qc_flagged_days"].sum() == 0
    pd.testing.assert_series_equal(a["precip_total_mm"], b["precip_total_mm"])
    pd.testing.assert_series_equal(a["precip_total_mm"], a["precip_total_mm_raw"], check_names=False)
