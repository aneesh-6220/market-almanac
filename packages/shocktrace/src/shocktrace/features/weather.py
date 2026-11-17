"""Leakage-safe weather anomaly features.

Anomaly of variable x for month t (calendar month m):

    z_t = (x_t - mu_m) / sigma_m

where (mu_m, sigma_m) is the *climatology* for calendar month m. Two reference modes:

* ``expanding`` (default): mu_m, sigma_m use only same-calendar-month values from years
  strictly before year(t). At every t the climatology uses information available at t, so
  the feature is point-in-time for training *and* test rows.
* ``fixed``: a fixed reference period [start_year, end_year]. To avoid leaking test-period
  climate information, the period must end before the first forecast-evaluation origin;
  ``check_fixed_climatology`` enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class LeakageError(ValueError):
    """Raised when a configuration would use information from the evaluation period."""


@dataclass(frozen=True)
class ClimatologyConfig:
    mode: str = "expanding"  # expanding | fixed
    fixed_start_year: int = 1991
    fixed_end_year: int = 2010
    min_years: int = 10

    def __post_init__(self) -> None:
        if self.mode not in ("expanding", "fixed"):
            raise ValueError("climatology mode must be 'expanding' or 'fixed'")
        if self.mode == "fixed" and self.fixed_end_year < self.fixed_start_year:
            raise ValueError("fixed climatology end year precedes start year")


def check_fixed_climatology(cfg: ClimatologyConfig, first_test_origin: pd.Timestamp) -> None:
    if cfg.mode == "fixed" and pd.Timestamp(year=cfg.fixed_end_year, month=12, day=1) >= first_test_origin:
        raise LeakageError(
            f"fixed climatology period ends {cfg.fixed_end_year}, which is not before the first test "
            f"origin {first_test_origin:%Y-%m}; this would leak evaluation-period climate information"
        )


def anomaly(x: pd.Series, cfg: ClimatologyConfig) -> pd.Series:
    """Standardised anomaly of a monthly series indexed by month-start timestamps."""
    x = x.sort_index()
    out = pd.Series(np.nan, index=x.index, dtype="float64")
    months = x.index.month
    for m in range(1, 13):
        s = x[months == m]
        if s.empty:
            continue
        if cfg.mode == "expanding":
            prior = s.shift(1)  # strictly earlier years
            mu = prior.expanding(min_periods=cfg.min_years).mean()
            sd = prior.expanding(min_periods=cfg.min_years).std()
        else:
            ref = s[(s.index.year >= cfg.fixed_start_year) & (s.index.year <= cfg.fixed_end_year)].dropna()
            if len(ref) < cfg.min_years:
                continue
            mu = pd.Series(ref.mean(), index=s.index)
            sd = pd.Series(ref.std(), index=s.index)
        z = (s - mu) / sd.replace(0, np.nan)
        out.loc[s.index] = z
    return out


def weather_features(w: pd.DataFrame, cfg: ClimatologyConfig) -> pd.DataFrame:
    """Compute monthly environmental features for one location.

    ``w`` columns: period, precip_total_mm, t2m_mean_c, t2m_max_mean_c, heat_days_t2m_max_ge_35c.
    Every feature at month t uses only months <= t.
    """
    w = w.set_index("period").sort_index()
    idx = pd.date_range(w.index.min(), w.index.max(), freq="MS")
    w = w.reindex(idx)
    rain = w["precip_total_mm"]
    rain3 = rain.rolling(3, min_periods=3).sum()
    rain6 = rain.rolling(6, min_periods=6).sum()
    heat3 = w["heat_days_t2m_max_ge_35c"].rolling(3, min_periods=3).sum()
    tmax3 = w["t2m_max_mean_c"].rolling(3, min_periods=3).mean()
    f = pd.DataFrame(index=idx)
    f["w_rain_anom_1"] = anomaly(rain, cfg)
    f["w_rain_anom_3"] = anomaly(rain3, cfg)
    f["w_rain_anom_6"] = anomaly(rain6, cfg)
    f["w_rain_anom_3_lag1"] = f["w_rain_anom_3"].shift(1)
    f["w_rain_anom_3_lag3"] = f["w_rain_anom_3"].shift(3)
    f["w_temp_anom_1"] = anomaly(w["t2m_mean_c"], cfg)
    f["w_tmax_anom_3"] = anomaly(tmax3, cfg)
    f["w_heat_days_3"] = heat3
    f["w_heat_anom_3"] = anomaly(heat3, cfg)
    f.index.name = "period"
    return f.reset_index()


WEATHER_FEATURES = (
    "w_rain_anom_1",
    "w_rain_anom_3",
    "w_rain_anom_6",
    "w_rain_anom_3_lag1",
    "w_rain_anom_3_lag3",
    "w_temp_anom_1",
    "w_tmax_anom_3",
    "w_heat_days_3",
    "w_heat_anom_3",
)
