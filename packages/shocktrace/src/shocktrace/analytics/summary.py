"""Series summaries and seasonality: the facts a visitor needs about one market-commodity series."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MIN_SEASONAL_YEARS = 3


def _months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _change(p: pd.Series, t: pd.Timestamp, k: int) -> dict[str, Any] | None:
    ref = t - pd.DateOffset(months=k)
    if ref not in p.index:
        return None
    return {
        "months": k,
        "reference_period": ref.date().isoformat(),
        "reference_price": float(p[ref]),
        "pct_change": float(p[t] / p[ref] - 1),
        "abs_change": float(p[t] - p[ref]),
    }


def series_summary(price: pd.Series, dataset_last_period: pd.Timestamp | None = None) -> dict[str, Any]:
    """Latest observation, recent changes, range and completeness for one monthly series.

    ``price`` is indexed by observation month (the month the price describes). The latest price
    is always reported with that observation month, never with the retrieval date.
    """
    p = price.where(price > 0).dropna().sort_index()
    if p.empty:
        return {"status": "no_valid_prices", "n_observations": 0}
    t = p.index[-1]
    first = p.index[0]
    span = _months_between(first, t) + 1
    # months before the series began are not "missing": the window starts no earlier than the first observation
    last24 = pd.date_range(max(first, t - pd.DateOffset(months=23)), t, freq="MS")
    recent = p.reindex(last24)
    last12 = p[p.index > t - pd.DateOffset(months=12)]
    stale = _months_between(t, dataset_last_period) if dataset_last_period is not None else None
    return {
        "status": "ok",
        "latest_period": t.date().isoformat(),
        "latest_price": float(p.iloc[-1]),
        "first_period": first.date().isoformat(),
        "n_observations": len(p),
        "months_spanned": span,
        "coverage": len(p) / span,
        "missing_months_last_24": int(recent.isna().sum()),
        "months_behind_dataset": stale,
        "changes": {f"m{k}": _change(p, t, k) for k in (1, 3, 12)},
        "range_12m": {
            "min": float(last12.min()),
            "max": float(last12.max()),
            "min_period": last12.idxmin().date().isoformat(),
            "max_period": last12.idxmax().date().isoformat(),
            "n": len(last12),
        },
        "all_time": {
            "min": float(p.min()),
            "max": float(p.max()),
            "min_period": p.idxmin().date().isoformat(),
            "max_period": p.idxmax().date().isoformat(),
        },
    }


def seasonal_profile(price: pd.Series) -> dict[str, Any]:
    """Typical within-year pattern: each month's price relative to its own calendar-year mean.

    For every calendar year with at least 9 observed months, index_m = P_m / mean(P in that
    year). The profile is the median index per calendar month across years (and the
    interquartile range), so a general upward trend does not masquerade as seasonality.
    """
    p = price.where(price > 0).dropna().sort_index()
    if p.empty:
        return {"status": "no_valid_prices", "months": []}
    df = pd.DataFrame({"p": p, "year": p.index.year, "month": p.index.month})
    counts = df.groupby("year")["p"].transform("count")
    full = df[counts >= 9].copy()
    if full["year"].nunique() < MIN_SEASONAL_YEARS:
        return {
            "status": "insufficient_history",
            "years_used": int(full["year"].nunique()),
            "months": [],
            "note": f"needs at least {MIN_SEASONAL_YEARS} calendar years with 9 or more observed months",
        }
    full["index"] = full["p"] / full.groupby("year")["p"].transform("mean")
    g = full.groupby("month")["index"]
    months: list[dict[str, Any]] = [
        {
            "month": int(m),
            "name": MONTH_NAMES[int(m) - 1],
            "median_index": float(v.median()),
            "q25": float(v.quantile(0.25)),
            "q75": float(v.quantile(0.75)),
            "n_years": len(v),
        }
        for m, v in g
    ]
    med: dict[int, float] = {int(m): float(v.median()) for m, v in g}
    hi = max(med, key=lambda k: med[k])
    lo = min(med, key=lambda k: med[k])
    t = p.index[-1]
    same = p[(p.index.month == t.month) & (p.index < t)]
    return {
        "status": "ok",
        "method": "median across years of price / calendar-year mean price, by calendar month",
        "years_used": int(full["year"].nunique()),
        "months": months,
        "peak_month": int(hi),
        "trough_month": int(lo),
        "seasonal_amplitude": float(med[hi] / med[lo] - 1),
        "same_month_history": [{"period": i.date().isoformat(), "price": float(v)} for i, v in same.tail(6).items()],
    }


def monthly_records(price: pd.Series) -> list[dict[str, Any]]:
    """Complete monthly index from first to last observation; missing months are explicit nulls."""
    p = price.sort_index()
    if p.empty:
        return []
    idx = pd.date_range(p.index.min(), p.index.max(), freq="MS")
    full = p.reindex(idx)
    return [
        {"period": i.date().isoformat(), "price": None if not np.isfinite(v) else float(v)} for i, v in full.items()
    ]
