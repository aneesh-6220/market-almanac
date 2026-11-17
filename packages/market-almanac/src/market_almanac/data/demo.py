"""Deterministic SYNTHETIC demonstration data.

Everything produced here is fictional and labelled ``provider="demo"`` / ``synthetic=True``.
"Demoland" (ISO-like code ``XDM``, currency ``XTS`` – the ISO 4217 code reserved for
testing) is an imaginary country whose markets are deliberately placed in the open
Atlantic Ocean so they can never be mistaken for real places.

The data-generating process is documented so that results on demo data can be interpreted
as *pipeline checks*, never as evidence about real markets:

* Weather: daily rainfall with a bimodal rainy season and persistent (AR(1)) monthly
  wetness anomalies; temperatures anti-correlated with rainfall anomalies.
* Maize (locally produced): log price follows an AR(1) deviation around trend + seasonality
  and responds to the previous three months' rainfall deficit and heat days. Here
  environmental information *is* predictive by construction.
* Rice (imported): responds to lagged exchange-rate depreciation, *not* to weather.
  Environmental features should not help here — a built-in negative control.
* Imperfections injected to exercise quality control: a gappy market, a market without
  coordinates, a reversing one-month spike, a series in a different unit, a short series and
  a conflicting duplicate record.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from market_almanac.data.identity import series_id, weather_location_id
from market_almanac.data.schema import AGRICULTURE, COUNTRIES, MACRO, PRICES, WEATHER_MONTHLY, coerce
from market_almanac.data.weather import aggregate_daily_to_monthly

SEED = 20240501
COUNTRY = "XDM"
COUNTRY_NAME = "Demoland (synthetic)"
CURRENCY = "XTS"
RETRIEVED_AT = pd.Timestamp("2025-12-31T00:00:00Z")
SOURCE_REF = "synthetic:market-almanac-demo-v1"
WEATHER_START, WEATHER_END = "1991-01-01", "2025-11-30"
PRICE_START, PRICE_END = "2012-01-01", "2025-11-01"


@dataclass(frozen=True)
class DemoMarket:
    code: str
    name: str
    admin1: str
    lat: float | None
    lon: float | None
    cell: int  # weather cell index


MARKETS = (
    DemoMarket("D001", "Port Aurel", "Coastal", 6.10, -24.20, 0),
    DemoMarket("D002", "Vell Junction", "Coastal", 6.35, -23.95, 0),
    DemoMarket("D003", "Highmoor", "Uplands", 7.60, -21.40, 1),
    DemoMarket("D004", "Saltbridge", "Uplands", 7.85, -21.10, 1),
    DemoMarket("D005", "Dunmere", "Drylands", 4.70, -22.60, 2),
    DemoMarket("D006", "Ashford Cross", "Drylands", 4.95, -22.30, 2),
    DemoMarket("D007", "Quarry Gate (no coordinates)", "Drylands", None, None, 2),
    DemoMarket("D008", "Fenwick (gappy)", "Uplands", 7.10, -21.80, 1),
)
CELL_CLIMATE = (  # (annual mean rain scale mm/day, base temp C)
    (4.2, 26.5),
    (3.0, 22.0),
    (1.6, 29.0),
)
RAIN_SEASON = np.array([0.35, 0.45, 1.25, 1.85, 1.55, 0.55, 0.30, 0.35, 0.55, 1.35, 1.60, 0.85])


def _weather(rng: np.random.Generator) -> tuple[pd.DataFrame, dict[int, pd.DataFrame]]:
    days = pd.date_range(WEATHER_START, WEATHER_END, freq="D")
    months = pd.date_range(WEATHER_START, WEATHER_END, freq="MS")
    monthly_by_cell: dict[int, pd.DataFrame] = {}
    frames: list[pd.DataFrame] = []
    # shared regional anomaly + cell-specific anomaly
    regional = np.zeros(len(months))
    for i in range(1, len(months)):
        regional[i] = 0.55 * regional[i - 1] + rng.normal(0, 0.8)
    for cell, (rain_scale, base_t) in enumerate(CELL_CLIMATE):
        local = np.zeros(len(months))
        for i in range(1, len(months)):
            local[i] = 0.4 * local[i - 1] + rng.normal(0, 0.5)
        wet = 0.75 * regional + 0.5 * local  # standardised-ish wetness anomaly
        mfac = pd.Series(np.exp(0.35 * wet), index=months)
        tanom = pd.Series(-0.45 * wet + rng.normal(0, 0.35, len(months)), index=months)
        mon = days.to_period("M").to_timestamp()
        season = RAIN_SEASON[days.month - 1]
        mean_rate = rain_scale * season * mfac.reindex(mon).to_numpy()
        wet_day = rng.random(len(days)) < np.clip(0.25 + 0.35 * season / RAIN_SEASON.max(), 0, 0.95)
        shape = 0.8
        amounts = rng.gamma(shape, 1.0, len(days))
        p_wet = np.clip(0.25 + 0.35 * season / RAIN_SEASON.max(), 0.05, 0.95)
        rain = np.where(wet_day, amounts * mean_rate / (shape * p_wet), 0.0)
        seas_t = 1.8 * np.cos(2 * np.pi * (days.month - 3) / 12)
        trend = 0.02 * (days.year - 1991)
        t2m = base_t + seas_t + trend + tanom.reindex(mon).to_numpy() + rng.normal(0, 0.9, len(days))
        tmax = t2m + 6.5 + rng.normal(0, 1.0, len(days)) - 0.15 * np.minimum(rain, 20)
        tmin = t2m - 6.0 + rng.normal(0, 0.8, len(days))
        daily = pd.DataFrame(
            {
                "date": days,
                "PRECTOTCORR": np.round(rain, 2),
                "T2M": np.round(t2m, 2),
                "T2M_MAX": np.round(tmax, 2),
                "T2M_MIN": np.round(tmin, 2),
            }
        )
        # sprinkle source-style missing days (fill values already converted to NaN)
        miss = rng.random(len(daily)) < 0.002
        daily.loc[miss, ["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN"]] = np.nan
        monthly = aggregate_daily_to_monthly(daily)
        monthly_by_cell[cell] = monthly
        rep = next(m for m in MARKETS if m.cell == cell and m.lat is not None)
        assert rep.lat is not None and rep.lon is not None
        from market_almanac.data.identity import power_grid_cell

        clat, clon = power_grid_cell(rep.lat, rep.lon)
        for mk in MARKETS:
            if mk.cell != cell or mk.lat is None or mk.lon is None:
                continue
            lid = weather_location_id(mk.lat, mk.lon)
            if any((f["location_id"].iloc[0] == lid) for f in frames):
                continue
            mlat, mlon = power_grid_cell(mk.lat, mk.lon)
            f = monthly.copy()
            f["location_id"], f["lat"], f["lon"] = lid, mlat, mlon
            frames.append(f)
        _ = (clat, clon)
    w = pd.concat(frames, ignore_index=True)
    w["provider"] = "demo"
    w["time_standard"] = "UTC"
    w["spatial_basis"] = "SYNTHETIC market-local geographic proxy"
    w["retrieved_at"] = RETRIEVED_AT
    return coerce(w, WEATHER_MONTHLY), monthly_by_cell


def _macro(rng: np.random.Generator) -> pd.DataFrame:
    months = pd.date_range("2008-01-01", PRICE_END, freq="MS")
    n = len(months)
    dlfx = 0.004 + rng.normal(0, 0.012, n)
    jumps = rng.random(n) < 0.02
    dlfx[jumps] += rng.uniform(0.06, 0.15, jumps.sum())
    lfx = np.log(80) + np.cumsum(dlfx)
    infl = 0.005 + 0.25 * np.concatenate([[0], dlfx[:-1]]) + rng.normal(0, 0.003, n)
    cpi = 100 * np.exp(np.cumsum(infl) - np.cumsum(infl)[months.get_loc(pd.Timestamp("2015-01-01"))])
    food = cpi * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    rows = []
    for code, name, unit, vals in (
        ("IMF.CPI.ALL", "Consumer price index, all items", "index", cpi),
        ("IMF.CPI.FOOD", "Consumer price index, food and non-alcoholic beverages", "index", food),
        (
            "IMF.FX.USD",
            "Exchange rate, national currency per US dollar, period average",
            "national currency per USD",
            np.exp(lfx),
        ),
    ):
        for p, v in zip(months, vals, strict=True):
            rows.append(
                {
                    "provider": "demo",
                    "country_iso3": COUNTRY,
                    "indicator_code": code,
                    "indicator_name": name,
                    "frequency": "M",
                    "period": p,
                    "value": float(np.round(v, 4)),
                    "unit": unit,
                    "source_ref": SOURCE_REF,
                    "published_at": pd.NaT,
                    "retrieved_at": RETRIEVED_AT,
                    "quality_flags": "synthetic",
                }
            )
    annual = pd.DataFrame(rows)
    a = annual[annual.indicator_code == "IMF.CPI.ALL"].copy()
    a["year"] = a["period"].dt.year
    ann_cpi = a.groupby("year")["value"].mean()
    for y in ann_cpi.index[1:]:
        if y > 2024:
            continue
        for code, name, unit, val in (
            (
                "FP.CPI.TOTL.ZG",
                "Inflation, consumer prices (annual %)",
                "% per year",
                100 * (ann_cpi[y] / ann_cpi[y - 1] - 1),
            ),
            ("SP.POP.TOTL", "Population, total", "people", 4_200_000 * 1.026 ** (y - 2008)),
            ("NY.GDP.PCAP.KD", "GDP per capita (constant 2015 US$)", "constant 2015 USD", 1450 * 1.018 ** (y - 2008)),
        ):
            rows.append(
                {
                    "provider": "demo",
                    "country_iso3": COUNTRY,
                    "indicator_code": code,
                    "indicator_name": name,
                    "frequency": "A",
                    "period": pd.Timestamp(year=int(y), month=1, day=1),
                    "value": float(round(val, 4)),
                    "unit": unit,
                    "source_ref": SOURCE_REF,
                    "published_at": pd.NaT,
                    "retrieved_at": RETRIEVED_AT,
                    "quality_flags": "synthetic",
                }
            )
    return coerce(pd.DataFrame(rows), MACRO)


def _standardize_by_month(x: pd.Series) -> pd.Series:
    g = x.groupby(x.index.month)
    return (x - g.transform("mean")) / g.transform("std")


def _prices(rng: np.random.Generator, monthly_by_cell: dict[int, pd.DataFrame], macro: pd.DataFrame) -> pd.DataFrame:
    months = pd.date_range(PRICE_START, PRICE_END, freq="MS")
    fx = macro[macro.indicator_code == "IMF.FX.USD"].set_index("period")["value"]
    dlfx = np.log(fx).diff().reindex(months).fillna(0).to_numpy()
    cpi = macro[macro.indicator_code == "IMF.CPI.ALL"].set_index("period")["value"].reindex(months).to_numpy()
    lcpi = np.log(cpi / cpi[0])
    rows = []
    seasonal_maize = 0.06 * np.cos(2 * np.pi * (months.month.to_numpy() - 7) / 12)  # lean-season peak mid-year
    national_shock = rng.normal(0, 0.012, len(months))
    for mk in MARKETS:
        wm = monthly_by_cell[mk.cell].set_index("period")
        rain_z = _standardize_by_month(wm["precip_total_mm"])
        rain3 = rain_z.rolling(3, min_periods=3).mean()
        heat = wm["heat_days_t2m_max_ge_35c"]
        heat_z = (
            (heat - heat.groupby(heat.index.month).transform("mean"))
            / heat.groupby(heat.index.month).transform("std").replace(0, np.nan)
        ).fillna(0)
        r3 = rain3.reindex(months).fillna(0).to_numpy()
        hz = heat_z.reindex(months).fillna(0).to_numpy()
        for commodity, code, cat, base in (
            ("Maize (white)", "DM-MAIZE", "cereals and tubers", 42.0),
            ("Rice (imported)", "DM-RICE", "cereals and tubers", 95.0),
        ):
            x = np.zeros(len(months))
            for i in range(1, len(months)):
                if code == "DM-MAIZE":
                    env = -0.045 * r3[i - 1] + 0.012 * hz[i - 1]
                    x[i] = 0.82 * x[i - 1] + env + national_shock[i] + rng.normal(0, 0.028)
                else:
                    x[i] = 0.85 * x[i - 1] + 0.35 * dlfx[i - 1] + 0.5 * national_shock[i] + rng.normal(0, 0.022)
            seas = seasonal_maize if code == "DM-MAIZE" else 0.01 * np.cos(2 * np.pi * months.month.to_numpy() / 12)
            mk_effect = rng.normal(0, 0.05)
            logp = np.log(base) + mk_effect + lcpi + seas + x
            price = np.round(np.exp(np.asarray(logp, dtype=float)), 2)
            unit, ptype = "KG", "Retail"
            keep = np.ones(len(months), dtype=bool)
            if mk.code == "D008":  # gappy market: drop a block of 9 months and random months
                keep[60:69] = False
                keep &= rng.random(len(months)) > 0.15
            if mk.code == "D006" and code == "DM-RICE":  # short series
                keep[: len(months) - 30] = False
            if mk.code == "D003" and code == "DM-MAIZE":  # reversing measurement spike
                price[100] = round(price[100] * 2.4, 2)
            for i, p in enumerate(months):
                if not keep[i]:
                    continue
                rows.append(_price_row(mk, commodity, code, cat, unit, ptype, p, float(price[i])))
            if mk.code == "D001" and code == "DM-MAIZE":  # same market, different unit -> separate series
                for i, p in enumerate(months[-48:]):
                    j = len(months) - 48 + i
                    rows.append(
                        _price_row(
                            mk, commodity, code, cat, "50 KG", "Wholesale", p, float(np.round(price[j] * 50 * 0.86, 2))
                        )
                    )
    df = pd.DataFrame(rows)
    # conflicting duplicate record for one series-month
    dup = df[(df.market_code == "D002") & (df.commodity_code == "DM-MAIZE")].iloc[[50]].copy()
    dup["price"] = dup["price"] * 1.3
    df = pd.concat([df, dup], ignore_index=True)
    conflict = df.duplicated(["series_id", "period"], keep=False)
    df["quality_flags"] = np.where(conflict, "synthetic,duplicate_conflict", "synthetic")
    return coerce(df, PRICES)


def _price_row(
    mk: DemoMarket, commodity: str, code: str, cat: str, unit: str, ptype: str, period: pd.Timestamp, price: float
) -> dict[str, object]:
    return {
        "series_id": series_id(
            provider="demo",
            country_iso3=COUNTRY,
            market_code=mk.code,
            commodity_code=code,
            unit=unit,
            price_type=ptype,
            price_flag="actual",
            currency=CURRENCY,
        ),
        "provider": "demo",
        "country_iso3": COUNTRY,
        "admin1_name": mk.admin1,
        "admin2_name": None,
        "market_code": mk.code,
        "market_name": mk.name,
        "lat": mk.lat,
        "lon": mk.lon,
        "commodity_code": code,
        "commodity_name": commodity,
        "commodity_category": cat,
        "unit": unit,
        "price_type": ptype,
        "price_flag": "actual",
        "currency": CURRENCY,
        "period": period,
        "price": price,
        "source_ref": SOURCE_REF,
        "reference_period_start": period + pd.Timedelta(days=14),
        "reference_period_end": period + pd.DateOffset(months=1) + pd.Timedelta(days=13),
        "published_at": pd.NaT,
        "retrieved_at": RETRIEVED_AT,
    }


def _agriculture(monthly_by_cell: dict[int, pd.DataFrame]) -> pd.DataFrame:
    w = pd.concat(monthly_by_cell.values()).groupby("period")["precip_total_mm"].mean()
    rows = []
    for y in range(2005, 2025):
        season_rain = w[(w.index.year == y) & (w.index.month.isin([3, 4, 5, 10, 11]))].sum()
        clim = (
            w[w.index.month.isin([3, 4, 5, 10, 11])]
            .groupby(w[w.index.month.isin([3, 4, 5, 10, 11])].index.year)
            .sum()
            .mean()
        )
        yld = 1650 * (season_rain / clim) ** 0.6 * 1.008 ** (y - 2005)
        area = 610_000 * 1.01 ** (y - 2005)
        for ec, en, unit, val in (
            ("5312", "Area harvested", "ha", area),
            ("5412", "Yield", "kg/ha", yld),
            ("5510", "Production", "t", area * yld / 1000),
        ):
            rows.append(
                {
                    "provider": "demo",
                    "country_iso3": COUNTRY,
                    "fao_area_code": "DEMO",
                    "domain_code": "QCL",
                    "item_code": "56",
                    "item_name": "Maize (corn)",
                    "element_code": ec,
                    "element_name": en,
                    "unit": unit,
                    "year": y,
                    "value": round(float(val), 1),
                    "flag": "S",
                    "flag_description": "Synthetic",
                    "source_ref": SOURCE_REF,
                    "published_at": pd.NaT,
                    "retrieved_at": RETRIEVED_AT,
                }
            )
    return coerce(pd.DataFrame(rows), AGRICULTURE)


def generate_demo_datasets(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    weather, by_cell = _weather(rng)
    macro = _macro(rng)
    prices = _prices(rng, by_cell, macro)
    agri = _agriculture(by_cell)
    countries = coerce(
        pd.DataFrame(
            [
                {
                    "iso3": COUNTRY,
                    "name": COUNTRY_NAME,
                    "region": "Synthetic region",
                    "income_level": "Synthetic",
                    "provider": "demo",
                    "retrieved_at": RETRIEVED_AT,
                }
            ]
        ),
        COUNTRIES,
    )
    return {"prices": prices, "weather_monthly": weather, "macro": macro, "agriculture": agri, "countries": countries}
