"""Crop geography (MapSPAM weights, crop calendars) and production-region weather features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_almanac.data.identity import power_grid_cell, weather_location_id
from market_almanac.experiments.config import ExperimentConfig
from market_almanac.experiments.runner import run_experiment
from market_almanac.features.builder import PRODUCTION_FEATURES
from market_almanac.features.production_weather import (
    MIN_WEIGHT_COVERAGE,
    build_production_features,
    production_index,
    season_features,
)
from market_almanac.geo.calendar import CropSeason, dekad_month, season_for
from market_almanac.geo.spam import (
    CROP_SPAM_CODES,
    CropGeographyError,
    cell_weights,
    check_weights,
    crop_for_commodity,
    packaged_weights,
    validate_crop_codes,
    validate_pixel_grid,
)

# --- crop geography -------------------------------------------------------------------------


def _pixels() -> pd.DataFrame:
    """Four 5-arcminute pixels: two share one POWER cell, one lies in another, one in a third."""
    codes = sorted({c for v in CROP_SPAM_CODES.values() for c in v})
    lon0, lat0 = -180 + (0.5 + 2141) / 12, -90 + (0.5 + 1228) / 12  # lattice centroids near 12.4N, -1.5E
    rows = [
        ("XAA", 1, lon0, lat0, 60.0, 0.0),
        ("XAA", 2, lon0 + 1 / 12, lat0, 30.0, 10.0),
        ("XAA", 3, lon0 + 1.0, lat0, 9.0, 0.0),
        ("XAA", 4, lon0, lat0 + 1.0, 1.0, 0.0),
        ("XBB", 5, lon0, lat0, 500.0, 500.0),  # another country: must never contribute
    ]
    df = pd.DataFrame(rows, columns=["iso3", "cell5m", "x", "y", "pmil_a", "smil_a"])
    for c in codes:
        if f"{c}_a" not in df:
            df[f"{c}_a"] = 0.0
    df["maiz_a"] = [5.0, 0.0, 0.0, 0.0, 0.0]
    return df


def test_weights_are_normalised_nonnegative_and_sum_millet_types():
    px = _pixels()
    w, s = cell_weights(px, "XAA", "millet", coverage=1.0)
    assert s.total_area_ha == pytest.approx(110.0)  # 60 + (30 + 10) + 9 + 1: pearl + small millet, XBB excluded
    assert w["weight"].sum() == pytest.approx(1.0, abs=1e-12) and (w["weight"] >= 0).all()
    home = weather_location_id(float(px["y"][0]), float(px["x"][0]))
    assert w.loc[w["location_id"] == home, "weight"].iloc[0] == pytest.approx(100 / 110)  # two pixels, one cell
    assert len(w) == 3
    check_weights(w)


def test_pixel_is_assigned_to_the_power_cell_containing_its_centroid():
    # 12.36N, -1.53E (Ouagadougou): floor(12.36/0.5)*0.5+0.25 = 12.25; floor(-1.53/0.625)*0.625+0.3125 = -1.5625
    assert power_grid_cell(12.36, -1.53) == pytest.approx((12.25, -1.5625))
    px = _pixels()
    w, _ = cell_weights(px, "XAA", "maize", coverage=1.0)
    lat, lon = power_grid_cell(float(px["y"][0]), float(px["x"][0]))
    assert list(w["lat"]) == [lat] and list(w["lon"]) == [lon] and w["weight"].iloc[0] == 1.0


def test_coverage_truncation_keeps_the_smallest_sufficient_set_and_renormalises():
    w, s = cell_weights(_pixels(), "XAA", "millet", coverage=0.95)
    # cells hold 100, 9 and 1 ha: the top two reach 99.1% >= 95%
    assert s.cells_total == 3 and s.cells_kept == 2
    assert s.area_share_kept == pytest.approx(109 / 110)
    assert w["weight"].tolist() == pytest.approx([100 / 109, 9 / 109])
    w1, s1 = cell_weights(_pixels(), "XAA", "millet", coverage=0.90)
    assert s1.cells_kept == 1 and w1["weight"].tolist() == [1.0]


def test_structural_validation_of_the_source():
    with pytest.raises(CropGeographyError):
        validate_crop_codes({"millet": ("pmil", "nope")})
    bad = _pixels()
    bad.loc[0, "x"] += 0.01  # off the 5-arcminute lattice: wrong projection or resolution
    with pytest.raises(CropGeographyError):
        validate_pixel_grid(bad)
    with pytest.raises(CropGeographyError):
        cell_weights(_pixels(), "XAA", "sorghum")  # crop not grown: refuse rather than invent weights
    with pytest.raises(CropGeographyError):
        check_weights(pd.DataFrame({"country_iso3": ["A"], "crop": ["m"], "location_id": ["x"], "weight": [0.9]}))


def test_commodity_names_map_to_crops():
    assert crop_for_commodity("Millet") == "millet"
    assert crop_for_commodity("Sorghum (white)") == "sorghum" and crop_for_commodity("Sorghum") == "sorghum"
    assert crop_for_commodity("Maize (white)") == "maize"
    assert crop_for_commodity("Beans (niebe)") == "cowpea"
    assert crop_for_commodity("Rice (imported)") is None and crop_for_commodity("Oil (vegetable)") is None


BBOX = {"BFA": (9.0, 15.5, -6.0, 2.8), "MLI": (10.0, 25.5, -12.6, 4.6), "NER": (11.5, 24.0, 0.0, 16.2)}


def test_packaged_weights_satisfy_their_invariants():
    w = packaged_weights()
    assert set(w["country_iso3"]) == set(BBOX)
    sums = w.groupby(["country_iso3", "crop"])["weight"].sum()
    assert np.allclose(sums, 1.0, atol=1e-8) and (w["weight"] > 0).all()
    assert set(w["crop"]) == {"millet", "sorghum", "maize", "cowpea"}
    assert (w["area_share_kept"] >= 0.95 - 1e-9).all()
    for iso, (s, n, west, east) in BBOX.items():
        c = w[w["country_iso3"] == iso]
        # POWER cell centres of pixels inside the country lie within half a cell of its bounding box
        assert c["lat"].between(s - 0.25, n + 0.25).all() and c["lon"].between(west - 0.32, east + 0.32).all()
    for r in w.sample(25, random_state=0).itertuples():
        assert r.location_id == weather_location_id(r.lat, r.lon)


# --- crop calendar --------------------------------------------------------------------------


def test_dekads_map_to_months():
    assert [dekad_month(d) for d in (1, 3, 4, 13, 31, 36)] == [1, 1, 2, 5, 11, 12]
    with pytest.raises(ValueError):
        dekad_month(37)


def test_calendar_seasons_follow_the_source():
    bfa = season_for("BFA", "millet")
    assert (bfa.sos_s, bfa.sos_e, bfa.eos_s, bfa.eos_e) == (13, 19, 31, 35)  # World Bank / JRC national entry
    assert bfa.season_months == (5, 6, 7, 8, 9, 10, 11) and bfa.harvest_end_month == 12 and bfa.basis == "source"
    assert season_for("NER", "sorghum").season_months == (6, 7, 8, 9, 10)
    assert season_for("MLI", "maize").season_months == (4, 5, 6, 7, 8, 9, 10)
    cow = season_for("BFA", "cowpea")  # absent from the source for Burkina Faso: documented millet fallback
    assert cow.basis == "fallback" and cow.season_months == bfa.season_months
    assert season_for("NER", "cowpea").basis == "source"
    assert season_for("XDM", "millet") is None


def test_a_season_may_wrap_the_year_end():
    s = CropSeason("XAA", "maize", sos_s=31, sos_e=33, eos_s=7, eos_e=9)  # planted November, harvested March
    assert s.season_months == (11, 12, 1, 2, 3) and s.wraps_year and s.harvest_end_month == 3


# --- production-weighted exposure and season features ----------------------------------------

SEASON = CropSeason("XAA", "millet", sos_s=16, sos_e=19, eos_s=27, eos_e=33)  # June..September, harvest ends November


def _weather(cells: dict[str, float], end: str = "2024-12-01", seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = pd.date_range("1991-01-01", end, freq="MS")
    out = []
    for loc, scale in cells.items():
        wet = np.isin(months.month, [6, 7, 8, 9])
        rain = np.where(wet, rng.gamma(6.0, 20.0, len(months)) * scale, 0.0)
        heat = np.where(np.isin(months.month, [3, 4, 5]), rng.integers(10, 30, len(months)), 2).astype(float)
        out.append(
            pd.DataFrame(
                {"location_id": loc, "period": months, "precip_total_mm": rain, "heat_days_t2m_max_ge_35c": heat}
            )
        )
    return pd.concat(out, ignore_index=True)


def test_production_index_is_the_weighted_mean_by_hand():
    wx = _weather({"a": 1.0, "b": 2.0})
    weights = pd.DataFrame({"location_id": ["a", "b"], "weight": [0.75, 0.25]})
    idx = production_index(wx, weights)
    t = pd.Timestamp("2010-07-01")
    xa = wx[(wx.location_id == "a") & (wx.period == t)]["precip_total_mm"].iloc[0]
    xb = wx[(wx.location_id == "b") & (wx.period == t)]["precip_total_mm"].iloc[0]
    assert idx.loc[t, "rain"] == pytest.approx(0.75 * xa + 0.25 * xb)
    assert idx.loc[t, "weight_coverage"] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        production_index(wx, pd.DataFrame({"location_id": ["a", "b"], "weight": [0.75, 0.5]}))


def test_missing_cells_are_renormalised_only_above_the_coverage_floor():
    wx = _weather({"a": 1.0, "b": 2.0, "c": 3.0})
    t = pd.Timestamp("2010-07-01")
    weights = pd.DataFrame({"location_id": ["a", "b", "c"], "weight": [0.6, 0.35, 0.05]})
    wx.loc[(wx.location_id == "c") & (wx.period == t), "precip_total_mm"] = np.nan  # 95% of weight remains
    idx = production_index(wx, weights)
    xa = wx[(wx.location_id == "a") & (wx.period == t)]["precip_total_mm"].iloc[0]
    xb = wx[(wx.location_id == "b") & (wx.period == t)]["precip_total_mm"].iloc[0]
    assert idx.loc[t, "rain"] == pytest.approx((0.6 * xa + 0.35 * xb) / 0.95)
    wx.loc[(wx.location_id == "b") & (wx.period == t), "precip_total_mm"] = np.nan  # only 60% remains
    assert MIN_WEIGHT_COVERAGE > 0.6 and np.isnan(production_index(wx, weights).loc[t, "rain"])


def _index(end: str = "2024-12-01") -> pd.DataFrame:
    return production_index(_weather({"a": 1.0}, end), pd.DataFrame({"location_id": ["a"], "weight": [1.0]}))


def test_season_to_date_anomaly_by_hand_and_same_stage_reference():
    idx = _index()
    f = season_features(idx, SEASON)
    # July 2020 is the second season month: compare June+July 2020 with June+July of 1991..2019
    cum = {y: idx.loc[f"{y}-06-01" : f"{y}-07-01", "rain"].sum() for y in range(1991, 2021)}
    prior = np.array([cum[y] for y in range(1991, 2020)])
    z = (cum[2020] - prior.mean()) / prior.std(ddof=1)
    assert f.loc["2020-07-01", "c_rain_season_anom"] == pytest.approx(np.clip(z, -4, 4))
    assert f.loc["2020-07-01", "c_rain_onset_anom"] == pytest.approx(np.clip(z, -4, 4))  # onset = first two months
    # after the season the value is frozen at the full-season anomaly until the next season starts
    full = {y: idx.loc[f"{y}-06-01" : f"{y}-09-01", "rain"].sum() for y in range(1991, 2021)}
    pf = np.array([full[y] for y in range(1991, 2020)])
    zf = np.clip((full[2020] - pf.mean()) / pf.std(ddof=1), -4, 4)
    for m in ("2020-09-01", "2020-12-01", "2021-05-01"):
        assert f.loc[m, "c_rain_season_anom"] == pytest.approx(zf)
    assert f.loc["2021-08-01", "c_rain_season_anom_prev"] == pytest.approx(zf)
    assert f.loc["2000-07-01", "c_rain_season_anom"] != f.loc["2001-07-01", "c_rain_season_anom"]
    assert np.isnan(f.loc["1999-07-01", "c_rain_season_anom"])  # fewer than 10 earlier seasons


def test_calendar_indicators_follow_the_season_definition():
    f = season_features(_index(), SEASON)
    y = f.loc["2015-01-01":"2015-12-01"]
    assert y["c_in_season"].tolist() == [0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0]
    # harvest ends in November: months since harvest are 0 in November, 1 in December, ... 11 in October
    assert y["c_months_since_harvest"].tolist() == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1]
    assert list(f.columns) == list(PRODUCTION_FEATURES)


def test_features_never_use_weather_after_the_information_month():
    idx = _index()
    cut = pd.Timestamp("2018-07-01")  # mid-season: the rest of the 2018 season is in the future
    alt = idx.copy()
    alt.loc[alt.index > cut, ["rain", "heat"]] *= 25.0
    a, b = season_features(idx, SEASON), season_features(alt, SEASON)
    pd.testing.assert_frame_equal(a.loc[:cut], b.loc[:cut])
    assert not np.allclose(a.loc["2018-09-01":"2019-06-01"], b.loc["2018-09-01":"2019-06-01"], equal_nan=True)


def test_build_features_keys_by_origin_and_respects_the_weather_lag(monkeypatch):
    import market_almanac.features.production_weather as pw

    monkeypatch.setattr(pw, "season_for", lambda iso, crop: SEASON)
    wx = _weather({"a": 1.0, "b": 0.5})
    weights = pd.DataFrame(
        {
            "country_iso3": "XAA",
            "crop": "millet",
            "location_id": ["a", "b"],
            "weight": [0.7, 0.3],
            "area_share_kept": 1.0,
        }
    )
    f0, meta = build_production_features(wx, "XAA", {"73": "Millet", "64": "Rice (imported)"}, weights=weights)
    f1, _ = build_production_features(wx, "XAA", {"73": "Millet"}, weights=weights, weather_release_lag=1)
    assert meta["crops"]["73"]["status"] == "ok" and meta["crops"]["73"]["cells_with_weather"] == 2
    assert "no production-region proxy" in meta["crops"]["64"]["status"]
    assert set(f0["commodity_code"]) == {"73"}
    a = f0.set_index("period").loc["2019-08-01", list(PRODUCTION_FEATURES)]
    b = f1.set_index("period").loc["2019-09-01", list(PRODUCTION_FEATURES)]
    pd.testing.assert_series_equal(a, b, check_names=False)  # origin t sees information month t-1
    # the wrong-crop falsification variant swaps weights/calendar but keeps the commodity key
    f2, m2 = build_production_features(wx, "XAA", {"67": "Maize"}, weights=weights, crop_override={"67": "millet"})
    assert set(f2["commodity_code"]) == {"67"} and m2["crops"]["67"]["crop"] == "millet"


def test_experiment_runs_three_way_comparison_on_matched_rows(demo_data):
    """A (price), B (market-local weather) and P (production-region) are compared on identical rows."""
    wx = demo_data["weather_monthly"]
    cells = sorted(wx["location_id"].unique())
    weights = pd.DataFrame({"location_id": cells, "weight": 1.0 / len(cells)})
    feats = season_features(production_index(wx, weights), SEASON).reset_index()
    prod = feats.assign(commodity_code="DM-MAIZE")
    cfg = ExperimentConfig(
        name="t",
        country_iso3="XDM",
        commodity_codes=["DM-MAIZE"],
        horizons=[1],
        families=["A", "B", "P"],
        include_trees=False,
        bootstrap_reps=100,
        sensitivity_thresholds=[0.10],
        price_release_lag_months=1,
    )
    out = run_experiment({**demo_data, "production_features": prod}, cfg, mode="demo", synthetic=True)
    reg = next(t for t in out.results["tasks"] if t["task"] == "regression")
    roles = {c["role"]: c for c in reg["comparisons"]}
    assert {"primary", "primary_production", "production_vs_local"} <= set(roles)
    assert roles["primary_production"]["model_b"] == "ridge_P" and roles["production_vs_local"]["model_a"] == "ridge_B"
    n = {roles[r]["n_rows"] for r in ("primary", "primary_production", "production_vs_local")}
    assert len(n) == 1  # identical evaluation rows for every contrast
    for r in ("primary", "primary_production", "production_vs_local"):
        assert roles[r]["dm"]["p_value_b_better_holm"] >= roles[r]["dm"]["p_value_b_better"]
        assert roles[r]["influence"]["status"] == "ok"
    assert out.results["multiplicity"]["n_tests"] == 6  # 3 contrasts x 2 tasks at one horizon
    assert "production_conclusion" in out.results and any("MapSPAM" in s for s in out.results["limitations"])
    p_cols = out.panel[list(PRODUCTION_FEATURES)]
    assert p_cols.notna().any().all()
