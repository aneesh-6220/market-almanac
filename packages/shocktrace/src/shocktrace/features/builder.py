"""Panel feature construction.

Builds one row per (series_id, origin month t). Every feature column is computable from
information available at the end of month t under the availability rules in
``shocktrace.data.alignment``. Targets are attached in separate ``y_*`` columns and are
never used as features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from shocktrace.data.alignment import RULES, asof_align
from shocktrace.data.identity import weather_location_id
from shocktrace.data.quality import clean_monthly_series
from shocktrace.features.weather import WEATHER_FEATURES, ClimatologyConfig, weather_features
from shocktrace.forecasting.targets import log_change_target, spike_target
from shocktrace.providers.faostat import fao_item_for_commodity

PRICE_FEATURES = ("p_dlog_1", "p_dlog_3", "p_dlog_12", "p_lag_dlog_1", "p_dev_12", "p_vol_6", "m_sin", "m_cos")
MACRO_FEATURES = ("m_cpi_yoy", "m_cpi_mom3", "m_food_cpi_yoy", "m_fx_dlog_1", "m_fx_dlog_3")
AGRI_FEATURES = ("a_prod_dlog", "a_yield_dev5", "a_area_dlog")

FEATURE_DOCS: dict[str, dict[str, str]] = {
    "p_dlog_1": {"family": "A", "source": "price", "desc": "ln P_t - ln P_{t-1}"},
    "p_dlog_3": {"family": "A", "source": "price", "desc": "ln P_t - ln P_{t-3}"},
    "p_dlog_12": {"family": "A", "source": "price", "desc": "ln P_t - ln P_{t-12}"},
    "p_lag_dlog_1": {"family": "A", "source": "price", "desc": "ln P_{t-1} - ln P_{t-2}"},
    "p_dev_12": {"family": "A", "source": "price", "desc": "ln P_t minus mean of ln P over t-11..t"},
    "p_vol_6": {"family": "A", "source": "price", "desc": "std. dev. of monthly log changes over t-5..t"},
    "m_sin": {"family": "A", "source": "calendar", "desc": "sin(2*pi*month(t)/12)"},
    "m_cos": {"family": "A", "source": "calendar", "desc": "cos(2*pi*month(t)/12)"},
    "p_seas_hist": {
        "family": "A",
        "source": "price",
        "desc": "mean of ln P_{t+h-12k} - ln P_{t-12k}, k=1..3 (same-season historical change)",
    },
    "w_rain_anom_1": {"family": "B", "source": "nasa_power", "desc": "rainfall anomaly, month t"},
    "w_rain_anom_3": {"family": "B", "source": "nasa_power", "desc": "3-month rainfall total anomaly ending t"},
    "w_rain_anom_6": {"family": "B", "source": "nasa_power", "desc": "6-month rainfall total anomaly ending t"},
    "w_rain_anom_3_lag1": {"family": "B", "source": "nasa_power", "desc": "3-month rainfall anomaly ending t-1"},
    "w_rain_anom_3_lag3": {"family": "B", "source": "nasa_power", "desc": "3-month rainfall anomaly ending t-3"},
    "w_temp_anom_1": {"family": "B", "source": "nasa_power", "desc": "mean temperature anomaly, month t"},
    "w_tmax_anom_3": {"family": "B", "source": "nasa_power", "desc": "3-month mean Tmax anomaly ending t"},
    "w_heat_days_3": {"family": "B", "source": "nasa_power", "desc": "days with Tmax >= 35C over t-2..t"},
    "w_heat_anom_3": {"family": "B", "source": "nasa_power", "desc": "anomaly of 3-month heat-day count"},
    "m_cpi_yoy": {"family": "C", "source": "imf", "desc": "12-month log change of headline CPI (2-month release lag)"},
    "m_cpi_mom3": {"family": "C", "source": "imf", "desc": "3-month log change of headline CPI (2-month lag)"},
    "m_food_cpi_yoy": {"family": "C", "source": "imf", "desc": "12-month log change of food CPI (2-month lag)"},
    "m_fx_dlog_1": {"family": "C", "source": "imf", "desc": "1-month log change, LCU per USD (1-month lag)"},
    "m_fx_dlog_3": {"family": "C", "source": "imf", "desc": "3-month log change, LCU per USD (1-month lag)"},
    "a_prod_dlog": {
        "family": "D",
        "source": "faostat",
        "desc": "annual log change in national production of the related crop (usable from Dec Y+1)",
    },
    "a_yield_dev5": {"family": "D", "source": "faostat", "desc": "ln yield_Y minus mean ln yield over Y-5..Y-1"},
    "a_area_dlog": {"family": "D", "source": "faostat", "desc": "annual log change in harvested area"},
}


def family_features(family: str, h: int) -> list[str]:
    a = [*PRICE_FEATURES, f"p_seas_hist_h{h}"]
    if family == "A":
        return a
    b = [*a, *WEATHER_FEATURES]
    if family == "B":
        return b
    c = [*b, *MACRO_FEATURES]
    if family == "C":
        return c
    if family == "D":
        return [*c, *AGRI_FEATURES]
    raise ValueError(f"unknown feature family {family}")


@dataclass
class FeatureBuildResult:
    panel: pd.DataFrame
    series_meta: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    availability: dict[str, Any] = field(default_factory=dict)


def _price_features(price: pd.Series, horizons: tuple[int, ...], thresholds: tuple[float, ...]) -> pd.DataFrame:
    lp = np.log(price.where(price > 0))
    d1 = lp.diff()
    f = pd.DataFrame(index=price.index)
    f["price"] = price
    f["log_price"] = lp
    f["p_dlog_1"] = d1
    f["p_dlog_3"] = lp - lp.shift(3)
    f["p_dlog_12"] = lp - lp.shift(12)
    f["p_lag_dlog_1"] = d1.shift(1)
    f["p_dev_12"] = lp - lp.rolling(12, min_periods=9).mean()
    f["p_vol_6"] = d1.rolling(6, min_periods=5).std()
    m = price.index.month
    f["m_sin"] = np.sin(2 * np.pi * m / 12)
    f["m_cos"] = np.cos(2 * np.pi * m / 12)
    for h in horizons:
        if h > 12:
            raise ValueError("horizons above 12 months are not supported by the seasonal features")
        # seasonal naive: the same-horizon change one year earlier (uses months <= t only)
        f[f"seasonal_naive_h{h}"] = lp.shift(12 - h) - lp.shift(12)
        hist = [lp.shift(12 * k - h) - lp.shift(12 * k) for k in (1, 2, 3)]
        f[f"p_seas_hist_h{h}"] = pd.concat(hist, axis=1).mean(axis=1, skipna=True)
        f[f"y_dlog_h{h}"] = log_change_target(price, h)
        for c in thresholds:
            f[f"y_spike_h{h}_t{round(c * 100)}"] = spike_target(price, h, c)
        f[f"target_period_h{h}"] = price.index + pd.DateOffset(months=h)
    return f


def _macro_derived(macro: pd.DataFrame, iso3: str) -> dict[str, pd.DataFrame]:
    """Derived monthly macro series (value at period a uses values <= a only)."""
    out: dict[str, pd.DataFrame] = {}
    m = macro[(macro["country_iso3"] == iso3) & (macro["frequency"] == "M")]
    for code, specs in (
        ("IMF.CPI.ALL", (("m_cpi_yoy", 12), ("m_cpi_mom3", 3))),
        ("IMF.CPI.FOOD", (("m_food_cpi_yoy", 12),)),
        ("IMF.FX.USD", (("m_fx_dlog_1", 1), ("m_fx_dlog_3", 3))),
    ):
        s = m[m["indicator_code"] == code].groupby("period")["value"].last().sort_index()
        if s.empty:
            continue
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))
        ls = np.log(s.where(s > 0))
        for name, k in specs:
            d = (ls - ls.shift(k)).dropna()
            out[name] = pd.DataFrame({"period": d.index, "value": d.values, "_code": code})
    return out


def _agri_derived(agri: pd.DataFrame, iso3: str, item_code: str) -> dict[str, pd.DataFrame]:
    a = agri[(agri["country_iso3"] == iso3) & (agri["item_code"] == item_code)]
    out: dict[str, pd.DataFrame] = {}
    if a.empty:
        return out
    piv = a.pivot_table(index="year", columns="element_code", values="value", aggfunc="last").sort_index()
    piv = piv.reindex(range(int(piv.index.min()), int(piv.index.max()) + 1))

    def frame(s: pd.Series) -> pd.DataFrame:
        s = s.dropna()
        return pd.DataFrame({"period": [pd.Timestamp(year=int(y), month=1, day=1) for y in s.index], "value": s.values})

    if "5510" in piv:
        out["a_prod_dlog"] = frame(np.log(piv["5510"]).diff())
    if "5412" in piv:
        ly = np.log(piv["5412"])
        out["a_yield_dev5"] = frame(ly - ly.shift(1).rolling(5, min_periods=3).mean())
    if "5312" in piv:
        out["a_area_dlog"] = frame(np.log(piv["5312"]).diff())
    return out


def build_panel(
    datasets: dict[str, pd.DataFrame],
    series_ids: list[str],
    horizons: tuple[int, ...] = (1, 3),
    thresholds: tuple[float, ...] = (0.10,),
    climatology: ClimatologyConfig | None = None,
) -> FeatureBuildResult:
    climatology = climatology or ClimatologyConfig()
    prices = datasets["prices"]
    weather = datasets.get("weather_monthly", pd.DataFrame())
    macro = datasets.get("macro", pd.DataFrame())
    agri = datasets.get("agriculture", pd.DataFrame())
    prices = prices[prices["series_id"].isin(series_ids)]
    if prices.empty:
        raise ValueError("no price records for the selected series")
    meta = prices.sort_values("retrieved_at").groupby("series_id").last().reset_index()
    monthly = clean_monthly_series(prices)
    warnings: list[str] = []
    wx_cache: dict[str, pd.DataFrame] = {}
    macro_cache: dict[str, dict[str, pd.DataFrame]] = {}
    rows = []
    for r in meta.itertuples():
        g = monthly[monthly["series_id"] == r.series_id].set_index("period")["price"]
        f = _price_features(g, horizons, thresholds)
        f.index.name = "period"
        # weather (market-local geographic proxy)
        if pd.notna(r.lat) and pd.notna(r.lon) and not weather.empty:
            loc = weather_location_id(float(r.lat), float(r.lon))
            if loc not in wx_cache:
                w = weather[weather["location_id"] == loc]
                wx_cache[loc] = weather_features(w, climatology) if len(w) else pd.DataFrame()
            wf = wx_cache[loc]
            if wf.empty:
                warnings.append(f"{r.series_id}: no weather for {loc}")
                for c in WEATHER_FEATURES:
                    f[c] = np.nan
            else:
                f = f.join(wf.set_index("period")[list(WEATHER_FEATURES)], how="left")
            f["location_id"] = loc
        else:
            for c in WEATHER_FEATURES:
                f[c] = np.nan
            f["location_id"] = None
        origins = pd.Series(f.index, index=f.index)
        # macro (as-of with conservative release lags)
        iso3 = r.country_iso3
        if iso3 not in macro_cache:
            macro_cache[iso3] = _macro_derived(macro, iso3) if not macro.empty else {}
        md = macro_cache[iso3]
        for name in MACRO_FEATURES:
            if name in md:
                rule = RULES["imf_fx"] if name.startswith("m_fx") else RULES["imf_cpi"]
                f[name] = asof_align(origins, md[name], rule, published_col=None).values
            else:
                f[name] = np.nan
        # agriculture (annual, as-of)
        item = fao_item_for_commodity(str(r.commodity_name))
        ad = _agri_derived(agri, iso3, item[0]) if (item and not agri.empty) else {}
        for name in AGRI_FEATURES:
            f[name] = (
                asof_align(origins, ad[name], RULES["faostat_annual"], published_col=None).values
                if name in ad
                else np.nan
            )
        f["series_id"] = r.series_id
        rows.append(f.reset_index().rename(columns={"period": "origin"}))
    panel = pd.concat(rows, ignore_index=True)
    for name in (*MACRO_FEATURES, *AGRI_FEATURES):
        if panel[name].isna().all():
            warnings.append(f"feature {name} unavailable for all series")
    availability = {
        "rules": {
            k: {
                "source": v.source,
                "frequency": v.frequency,
                "release_lag_months": v.release_lag_months,
                "basis": v.basis,
            }
            for k, v in RULES.items()
        },
        "climatology": climatology.__dict__,
        "features": FEATURE_DOCS,
        "spatial_basis": "Weather is a market-local geographic proxy, not production-area exposure.",
    }
    return FeatureBuildResult(panel=panel, series_meta=meta, warnings=warnings, availability=availability)
