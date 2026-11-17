"""Daily -> monthly weather aggregation with precipitation quality control (provider independent).

Rules (documented in docs/METHODOLOGY.md §3):

* A month is *complete* when at least 90% of its calendar days have valid observations.
* Incomplete months (including the current, partially-elapsed month) get NaN aggregates;
  they are never extrapolated from a handful of days.
* For complete months with a few missing days, precipitation total = mean daily rate x
  days in month (proportional infill); heat-day counts are scaled the same way.
* Heat stress: number of days with daily maximum 2 m temperature >= 35 °C, a commonly used
  absolute crop heat-stress threshold for maize/cereals. It is a screening indicator, not a
  crop model.

Precipitation QC (``precip-qc-1``)
----------------------------------
Reanalysis precipitation occasionally contains values that are climatologically implausible for
the place and season. The motivating case is MERRA-2 corrected precipitation of 36-515 mm/day on
2025-12-02 over nine adjacent cells of south-west Burkina Faso (dry season), where IMERG reports
1.6 mm and CHIRPS v3 under 4 mm (docs/audits/evidence/rainfall_2025_12_02.json). Because the
artefact is spatially coherent, a neighbour-consistency check cannot detect it; the screen below
is therefore climatological and per cell.

A daily value v is *flagged* when both hold:

1. v >= ``PRECIP_QC_ABS_FLOOR_MM`` (50 mm, the conventional "very heavy rain" day), and
2. v > ``PRECIP_QC_RECORD_FACTOR`` (2) x R, where R is the largest unflagged daily value the same
   cell recorded in the three-calendar-month window centred on the day's month, in years
   strictly before the day's year (at least ``PRECIP_QC_MIN_PRIOR_YEARS`` such years).

The rule uses only earlier years, so it is computable in real time. Flagged days are **not**
deleted: the raw monthly total is kept in ``precip_total_mm_raw``, the number of flagged days in
``precip_qc_flagged_days`` and the largest flagged value in ``precip_qc_max_flagged_mm``. The
QC'd total ``precip_total_mm`` treats flagged days as missing (proportional infill; the month
becomes NaN if fewer than 90% of its days remain). The constants were fixed from the physical
argument above, not tuned against forecast results; flag counts under other factors are
reported by ``scripts/audit/precip_qc_report.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COMPLETENESS_THRESHOLD = 0.9
HEAT_THRESHOLD_C = 35.0

PRECIP_QC_VERSION = "precip-qc-1"
PRECIP_QC_ABS_FLOOR_MM = 50.0
PRECIP_QC_RECORD_FACTOR = 2.0
PRECIP_QC_MIN_PRIOR_YEARS = 10

MONTHLY_COLUMNS = [
    "period",
    "precip_total_mm",
    "t2m_mean_c",
    "t2m_max_mean_c",
    "t2m_min_mean_c",
    "heat_days_t2m_max_ge_35c",
    "days_observed",
    "days_in_month",
    "complete",
    "precip_total_mm_raw",
    "precip_qc_flagged_days",
    "precip_qc_max_flagged_mm",
]


def flag_implausible_precipitation(
    dates: pd.Series,
    precip: pd.Series,
    *,
    abs_floor: float = PRECIP_QC_ABS_FLOOR_MM,
    factor: float = PRECIP_QC_RECORD_FACTOR,
    min_prior_years: int = PRECIP_QC_MIN_PRIOR_YEARS,
) -> np.ndarray:
    """Boolean mask of climatologically implausible daily precipitation (see module docstring).

    Years are processed in order; each year is judged against records set by *earlier* years
    only, and flagged values never enter the record used for later years.
    """
    d = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    v = pd.to_numeric(pd.Series(precip).reset_index(drop=True), errors="coerce").to_numpy(dtype=float)
    years = d.dt.year.to_numpy()
    months = d.dt.month.to_numpy()
    flagged = np.zeros(len(v), dtype=bool)
    record = np.full(13, np.nan)  # record[m] = largest unflagged value seen in calendar month m
    years_seen = 0
    for y in np.unique(years):
        in_year = years == y
        if years_seen >= min_prior_years:
            for m in range(1, 13):
                rows = np.flatnonzero(in_year & (months == m))
                if rows.size == 0:
                    continue
                window = [(m - 2) % 12 + 1, m, m % 12 + 1]
                ref = record[window]
                if np.all(np.isnan(ref)):
                    continue
                limit = factor * float(np.nanmax(ref))
                vals = v[rows]
                flagged[rows] = np.isfinite(vals) & (vals >= abs_floor) & (vals > limit)
        ok = in_year & ~flagged & np.isfinite(v)
        if ok.any():
            for m in np.unique(months[ok]):
                top = float(v[ok & (months == m)].max())
                record[m] = top if np.isnan(record[m]) else max(record[m], top)
            years_seen += 1
    return flagged


def aggregate_daily_to_monthly(daily: pd.DataFrame, *, precip_qc: bool = True) -> pd.DataFrame:
    """Aggregate a daily frame with columns date, PRECTOTCORR, T2M, T2M_MAX, T2M_MIN.

    Missing values must already be NaN (fill-value sentinels removed). With ``precip_qc`` the
    QC'd precipitation total excludes flagged days; the raw total is always reported alongside.
    """
    if daily.empty:
        return pd.DataFrame(columns=MONTHLY_COLUMNS)
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    d["period"] = d["date"].dt.to_period("M").dt.to_timestamp()
    valid = d[["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN"]].notna().all(axis=1)
    d["heat"] = np.where(d["T2M_MAX"].notna(), (d["T2M_MAX"] >= HEAT_THRESHOLD_C).astype(float), np.nan)
    flag = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"]) if precip_qc else np.zeros(len(d), dtype=bool)
    d["flag"] = flag & valid.to_numpy()
    d["precip_qc"] = d["PRECTOTCORR"].where(~d["flag"])
    g = d[valid].groupby("period")
    agg = pd.DataFrame(
        {
            "precip_mean_raw": g["PRECTOTCORR"].mean(),
            "precip_mean_qc": g["precip_qc"].mean(),
            "precip_days_qc": g["precip_qc"].count(),
            "t2m_mean_c": g["T2M"].mean(),
            "t2m_max_mean_c": g["T2M_MAX"].mean(),
            "t2m_min_mean_c": g["T2M_MIN"].mean(),
            "heat_rate": g["heat"].mean(),
            "days_observed": g.size(),
            "precip_qc_flagged_days": g["flag"].sum(),
        }
    )
    agg["precip_qc_max_flagged_mm"] = d[d["flag"]].groupby("period")["PRECTOTCORR"].max()
    all_periods = pd.Index(sorted(d["period"].unique()), name="period")
    agg = agg.reindex(all_periods)
    agg["days_observed"] = agg["days_observed"].fillna(0).astype(int)
    agg["precip_days_qc"] = agg["precip_days_qc"].fillna(0).astype(int)
    agg["precip_qc_flagged_days"] = agg["precip_qc_flagged_days"].fillna(0).astype(int)
    agg["days_in_month"] = [p.days_in_month for p in agg.index]
    agg["complete"] = agg["days_observed"] >= COMPLETENESS_THRESHOLD * agg["days_in_month"]
    agg["precip_total_mm_raw"] = agg["precip_mean_raw"] * agg["days_in_month"]
    agg["precip_total_mm"] = agg["precip_mean_qc"] * agg["days_in_month"]
    agg["heat_days_t2m_max_ge_35c"] = agg["heat_rate"] * agg["days_in_month"]
    value_cols = [
        "precip_total_mm",
        "precip_total_mm_raw",
        "t2m_mean_c",
        "t2m_max_mean_c",
        "t2m_min_mean_c",
        "heat_days_t2m_max_ge_35c",
    ]
    agg.loc[~agg["complete"], value_cols] = np.nan
    # QC'd precipitation needs its own completeness: flagged days count as missing.
    agg.loc[agg["precip_days_qc"] < COMPLETENESS_THRESHOLD * agg["days_in_month"], "precip_total_mm"] = np.nan
    return agg.reset_index()[MONTHLY_COLUMNS]
