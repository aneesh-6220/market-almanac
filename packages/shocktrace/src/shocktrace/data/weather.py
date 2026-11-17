"""Daily -> monthly weather aggregation (provider independent).

Rules (documented in docs/METHODOLOGY.md §3):

* A month is *complete* when at least 90% of its calendar days have valid observations.
* Incomplete months (including the current, partially-elapsed month) get NaN aggregates;
  they are never extrapolated from a handful of days.
* For complete months with a few missing days, precipitation total = mean daily rate x
  days in month (proportional infill); heat-day counts are scaled the same way.
* Heat stress: number of days with daily maximum 2 m temperature >= 35 °C, a commonly used
  absolute crop heat-stress threshold for maize/cereals. It is a screening indicator, not a
  crop model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COMPLETENESS_THRESHOLD = 0.9
HEAT_THRESHOLD_C = 35.0


def aggregate_daily_to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a daily frame with columns date, PRECTOTCORR, T2M, T2M_MAX, T2M_MIN.

    Missing values must already be NaN (fill-value sentinels removed).
    """
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "period",
                "precip_total_mm",
                "t2m_mean_c",
                "t2m_max_mean_c",
                "t2m_min_mean_c",
                "heat_days_t2m_max_ge_35c",
                "days_observed",
                "days_in_month",
                "complete",
            ]
        )
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["period"] = d["date"].dt.to_period("M").dt.to_timestamp()
    valid = d[["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN"]].notna().all(axis=1)
    d["heat"] = np.where(d["T2M_MAX"].notna(), (d["T2M_MAX"] >= HEAT_THRESHOLD_C).astype(float), np.nan)
    g = d[valid].groupby("period")
    agg = pd.DataFrame(
        {
            "precip_mean": g["PRECTOTCORR"].mean(),
            "t2m_mean_c": g["T2M"].mean(),
            "t2m_max_mean_c": g["T2M_MAX"].mean(),
            "t2m_min_mean_c": g["T2M_MIN"].mean(),
            "heat_rate": g["heat"].mean(),
            "days_observed": g.size(),
        }
    )
    all_periods = pd.Index(sorted(d["period"].unique()), name="period")
    agg = agg.reindex(all_periods)
    agg["days_observed"] = agg["days_observed"].fillna(0).astype(int)
    agg["days_in_month"] = [p.days_in_month for p in agg.index]
    agg["complete"] = agg["days_observed"] >= COMPLETENESS_THRESHOLD * agg["days_in_month"]
    agg["precip_total_mm"] = agg["precip_mean"] * agg["days_in_month"]
    agg["heat_days_t2m_max_ge_35c"] = agg["heat_rate"] * agg["days_in_month"]
    value_cols = ["precip_total_mm", "t2m_mean_c", "t2m_max_mean_c", "t2m_min_mean_c", "heat_days_t2m_max_ge_35c"]
    agg.loc[~agg["complete"], value_cols] = np.nan
    return agg.reset_index()[["period", *value_cols, "days_observed", "days_in_month", "complete"]]
