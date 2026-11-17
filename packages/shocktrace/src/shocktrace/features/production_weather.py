"""Production-region, crop-season-aware weather features (feature family P).

Step 1 - production-weighted exposure. For crop c with weights w(c, i) over NASA POWER cells i
(``shocktrace.geo.spam``) and a monthly weather variable X(i, t):

    W(c, t) = sum_i w(c, i) * X(i, t)

If some cells are missing in month t the sum is renormalised over the available cells, provided
they carry at least ``MIN_WEIGHT_COVERAGE`` of the weight; otherwise W(c, t) is missing.

Step 2 - season alignment. The crop calendar (``shocktrace.geo.calendar``) gives the growing
season's calendar months. For an *information month* m (the latest complete weather month a
forecaster holds), let s be the most recent season that has started by m and k the number of
its months elapsed by m (capped at the season length n). Features compare the season so far
with the same stage of earlier seasons only:

    z(s, k) = (C(s, k) - mean_{s' < s} C(s', k)) / sd_{s' < s} C(s', k),   clipped to +/-4

where C(s, k) is W cumulated over the first k months of season s. Because the reference uses
earlier seasons at the same stage, an unfinished season is never compared with completed ones
and no weather after m is used.

    c_rain_season_anom       z(s, min(k, n)) of rainfall: season to date; final value after harvest
    c_rain_season_anom_prev  z(s - 1, n) of rainfall: the previous completed season
    c_heat_season_anom       z(s, min(k, n)) of days with Tmax >= 35C
    c_rain_onset_anom        z(s, min(k, 2)) of rainfall: the first two months of the season
    c_in_season              1 if m lies in the growing season, else 0
    c_months_since_harvest   months from the harvest-end month to m (0..11)

These are *proxies*. MapSPAM shows where a crop was grown around 2010 across the country; it
does not identify the farms supplying a market, and imports, stocks, transport and conflict are
not represented.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

from shocktrace.features.builder import PRODUCTION_FEATURES
from shocktrace.features.weather import ANOMALY_CLIP, ClimatologyConfig
from shocktrace.geo.calendar import CropSeason, season_for
from shocktrace.geo.spam import crop_for_commodity, packaged_weights

MIN_WEIGHT_COVERAGE = 0.9
ONSET_MONTHS = 2
EXPOSURE_COLUMNS = {"rain": "precip_total_mm", "heat": "heat_days_t2m_max_ge_35c"}


def production_index(weather: pd.DataFrame, weights: pd.DataFrame, use_precip_qc: bool = True) -> pd.DataFrame:
    """Production-weighted monthly exposure W(c, t) for one country and crop.

    ``weights``: columns location_id, weight (non-negative, summing to 1).
    Returns a frame indexed by month with columns rain, heat and weight_coverage.
    """
    w = weights.set_index("location_id")["weight"].astype(float)
    if (w < 0).any() or abs(w.sum() - 1) > 1e-6:
        raise ValueError("production weights must be non-negative and sum to 1")
    wx = weather[weather["location_id"].isin(w.index)]
    if wx.empty:
        return pd.DataFrame(columns=["rain", "heat", "weight_coverage"])
    cols = dict(EXPOSURE_COLUMNS)
    if not use_precip_qc and "precip_total_mm_raw" in wx:
        wx = wx.assign(precip_total_mm=wx["precip_total_mm_raw"].fillna(wx["precip_total_mm"]))
    idx = pd.date_range(wx["period"].min(), wx["period"].max(), freq="MS")
    out = pd.DataFrame(index=idx)
    for name, col in cols.items():
        wide = wx.pivot_table(index="period", columns="location_id", values=col, aggfunc="last").reindex(idx)
        wide = wide.reindex(columns=w.index)
        avail = wide.notna().to_numpy()
        cover = avail @ w.to_numpy()
        total = np.nansum(wide.to_numpy(dtype=float) * w.to_numpy(), axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            val = np.where(cover >= MIN_WEIGHT_COVERAGE, total / cover, np.nan)
        out[name] = val
        if name == "rain":
            out["weight_coverage"] = cover
    out.index.name = "period"
    return out


def _season_position(months: pd.DatetimeIndex, season: CropSeason) -> tuple[np.ndarray, np.ndarray]:
    """For each month: the label (start year) of the most recent started season and months elapsed in it."""
    start = season.start_month
    year, month = months.year.to_numpy(), months.month.to_numpy()
    season_year = np.where(month >= start, year, year - 1)
    elapsed = (year - season_year) * 12 + (month - start) + 1  # 1 in the season's first month
    return season_year, elapsed


def _stage_table(x: pd.Series, season: CropSeason) -> pd.DataFrame:
    """C(s, k): x cumulated over the first k months of season s (rows s, columns k = 1..n)."""
    n = len(season.season_months)
    sy, k = _season_position(pd.DatetimeIndex(x.index), season)
    d = pd.DataFrame({"s": sy, "k": k, "x": x.to_numpy(dtype=float)})
    d = d[d["k"] <= n]
    wide = d.pivot_table(index="s", columns="k", values="x", aggfunc="first").reindex(columns=range(1, n + 1))
    return wide.cumsum(axis=1, skipna=False)  # a missing month makes later stages missing


def _stage_anomaly(table: pd.DataFrame, min_years: int) -> pd.DataFrame:
    """z(s, k) against earlier seasons at the same stage (expanding, prior seasons only), clipped."""
    prior = table.shift(1)
    mu = prior.expanding(min_periods=min_years).mean()
    sd = prior.expanding(min_periods=min_years).std()
    return ((table - mu) / sd.replace(0, np.nan)).clip(-ANOMALY_CLIP, ANOMALY_CLIP)


def season_features(index: pd.DataFrame, season: CropSeason, cfg: ClimatologyConfig | None = None) -> pd.DataFrame:
    """Family-P features per information month (see module docstring). Index: month."""
    cfg = cfg or ClimatologyConfig()
    if cfg.mode != "expanding":
        raise ValueError("production-region features support the expanding (prior seasons only) climatology")
    months = pd.DatetimeIndex(index.index)
    n = len(season.season_months)
    sy, k = _season_position(months, season)
    stage = np.minimum(k, n)
    z_rain = _stage_anomaly(_stage_table(index["rain"], season), cfg.min_years)
    z_heat = _stage_anomaly(_stage_table(index["heat"], season), cfg.min_years)

    def look(z: pd.DataFrame, s: np.ndarray, kk: np.ndarray) -> np.ndarray:
        pos_s = z.index.get_indexer(s)
        vals = z.to_numpy()
        out = np.full(len(s), np.nan)
        ok = pos_s >= 0
        out[ok] = vals[pos_s[ok], kk[ok] - 1]
        return out

    f = pd.DataFrame(index=months)
    f["c_rain_season_anom"] = look(z_rain, sy, stage)
    f["c_rain_season_anom_prev"] = look(z_rain, sy - 1, np.full(len(sy), n))
    f["c_heat_season_anom"] = look(z_heat, sy, stage)
    f["c_rain_onset_anom"] = look(z_rain, sy, np.minimum(k, ONSET_MONTHS))
    f["c_in_season"] = (k <= n).astype(float)
    f["c_months_since_harvest"] = ((months.month.to_numpy() - season.harvest_end_month) % 12).astype(float)
    f.index.name = "period"
    return f[list(PRODUCTION_FEATURES)]


def weights_fingerprint(weights: pd.DataFrame) -> str:
    cols = ["country_iso3", "crop", "location_id", "weight"]
    w = weights[cols].sort_values(cols[:3]).round({"weight": 10})
    return hashlib.sha256(w.to_csv(index=False).encode()).hexdigest()[:16]


def build_production_features(
    weather: pd.DataFrame,
    country_iso3: str,
    commodities: dict[str, str],
    climatology: ClimatologyConfig | None = None,
    *,
    weather_release_lag: int = 0,
    weights: pd.DataFrame | None = None,
    use_precip_qc: bool = True,
    crop_override: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Family-P features for each commodity of a country, keyed by forecast origin.

    ``commodities`` maps commodity_code -> commodity name. The row with ``period = t`` uses
    weather up to the information month ``t - weather_release_lag`` only.
    ``crop_override`` (commodity_code -> crop key) substitutes another crop's weights and
    calendar; it exists for the wrong-crop falsification check.
    """
    weights = packaged_weights() if weights is None else weights
    frames: list[pd.DataFrame] = []
    meta: dict[str, Any] = {"weights_fingerprint": weights_fingerprint(weights) if len(weights) else None, "crops": {}}
    for code, name in commodities.items():
        crop = (crop_override or {}).get(code) or crop_for_commodity(name)
        info: dict[str, Any] = {"commodity_name": name, "crop": crop}
        meta["crops"][code] = info
        if crop is None:
            info["status"] = "no production-region proxy defined for this commodity"
            continue
        w = weights[(weights["country_iso3"] == country_iso3) & (weights["crop"] == crop)]
        season = season_for(country_iso3, crop)
        if w.empty or season is None:
            info["status"] = "no crop weights" if w.empty else "no crop calendar"
            continue
        idx = production_index(weather, w, use_precip_qc)
        if idx.empty or idx["rain"].notna().sum() == 0:
            info["status"] = "no weather stored for the production cells"
            continue
        f = season_features(idx, season, climatology)
        if weather_release_lag:
            f = f.reindex(
                pd.date_range(f.index.min(), f.index.max() + pd.DateOffset(months=weather_release_lag), freq="MS")
            ).shift(weather_release_lag)
            f.index.name = "period"
        cells_with_weather = int(w["location_id"].isin(weather["location_id"].unique()).sum())
        info.update(
            {
                "status": "ok",
                "cells": len(w),
                "cells_with_weather": cells_with_weather,
                "min_weight_coverage": float(idx["weight_coverage"].min()),
                "area_share_kept": float(w["area_share_kept"].iloc[0]) if "area_share_kept" in w else None,
                "season_months": list(season.season_months),
                "harvest_end_month": season.harvest_end_month,
                "calendar_basis": season.basis,
            }
        )
        frames.append(f.reset_index().assign(commodity_code=str(code)))
    cols = ["commodity_code", "period", *PRODUCTION_FEATURES]
    out = pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)
    return out, meta
