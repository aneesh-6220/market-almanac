"""Validated economic transformations. Pure functions on monthly pandas Series; each has a stated definition.

Conventions
-----------
* A *monthly series* has a ``DatetimeIndex`` of month starts. Missing months are simply absent (or NaN) and are
  **never filled or interpolated**: a change is computed only when both end points were observed, and a change is
  never computed across a gap by silently shifting positions (everything is calendar-based: ``t`` against ``t - k``
  months).
* **Index levels versus price levels.** CPI and benchmark series are levels; changes are ratios of levels. Only
  ratios of the *same* series are taken, so the base year of an index never matters (tested: rebasing leaves every
  change unchanged). Two different series' levels are never added, averaged or compared directly.
* **Quote direction.** Exchange rates here are *domestic currency per one US dollar*. A rise means the dollar
  became more expensive in domestic currency, i.e. the domestic currency became weaker **against the dollar**. That
  statement concerns one bilateral rate; it is not a claim about the currency's value against anything else, and it
  is not by itself "depreciation" of an economy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# A 12-month movement of at least this size is described as a material change in the context sections. It is a
# reporting convention, not a statistical test, and every statement that uses it names the actual number too.
MATERIAL_CHANGE = 0.10
# A one-month move of at least this size in a level series that coincides with a base-year change is treated as a
# discontinuity of the index (a rebase that was not spliced), not as inflation.
BASE_BREAK_MOM = 0.25
# A one-month move in an exchange rate of at least this size is reported as a step change (revaluation, float,
# unification of rates), not as a gradual movement.
FX_STEP_MOM = 0.25
MIN_LAG_OBS = 24


class TransformError(ValueError):
    """The input violates a precondition of the transformation (the message says which)."""


def as_monthly(s: pd.Series, name: str = "series") -> pd.Series:
    """Validate and normalise: month-start DatetimeIndex, sorted, unique, float values, no infinities."""
    if not isinstance(s.index, pd.DatetimeIndex):
        raise TransformError(f"{name}: index must be a DatetimeIndex")
    idx = s.index.to_period("M").to_timestamp()
    if idx.has_duplicates:
        raise TransformError(f"{name}: duplicate months")
    out = pd.Series(s.to_numpy(dtype=float), index=idx, name=s.name).sort_index()
    out = out.replace([np.inf, -np.inf], np.nan)
    return out


def _calendar(s: pd.Series) -> pd.Series:
    s = as_monthly(s)
    if s.empty:
        return s
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))


# --- changes of an index or price level -----------------------------------------------------------------------


def pct_change(s: pd.Series, months: int, breaks: list[pd.Timestamp] | None = None) -> pd.Series:
    """``s_t / s_{t-months} - 1`` where both months were observed and the earlier level is positive.

    ``breaks`` are months at which the level series is discontinuous (see :func:`find_base_breaks`): a change whose
    window ``(t - months, t]`` contains a break month is NaN, because the two levels are on different bases.
    """
    if months < 1:
        raise TransformError("months must be >= 1")
    full = _calendar(s)
    prev = full.shift(months)
    out = full / prev.where(prev > 0) - 1.0
    for b in breaks or []:
        b = pd.Timestamp(b).to_period("M").to_timestamp()
        # t is affected when t - months < b <= t, i.e. b lies in (t - months, t]
        hit = (out.index >= b) & (out.index < b + pd.DateOffset(months=months))
        out[hit] = np.nan
    return out


def mom_pct(s: pd.Series, breaks: list[pd.Timestamp] | None = None) -> pd.Series:
    """Month-over-month change of a level series: ``s_t / s_{t-1} - 1``."""
    return pct_change(s, 1, breaks)


def yoy_pct(s: pd.Series, breaks: list[pd.Timestamp] | None = None) -> pd.Series:
    """Year-over-year change of a monthly level series: ``s_t / s_{t-12} - 1`` (not an annual-frequency value)."""
    return pct_change(s, 12, breaks)


def change_between(
    s: pd.Series, start: pd.Timestamp, end: pd.Timestamp, breaks: list[pd.Timestamp] | None = None
) -> float | None:
    """Total change from month ``start`` to month ``end`` (both observed, no break between them), else None."""
    s = as_monthly(s)
    a, b = pd.Timestamp(start).to_period("M").to_timestamp(), pd.Timestamp(end).to_period("M").to_timestamp()
    if a not in s.index or b not in s.index or pd.isna(s[a]) or pd.isna(s[b]) or s[a] <= 0:
        return None
    for br in breaks or []:
        if a < pd.Timestamp(br) <= b:
            return None
    return float(s[b] / s[a] - 1.0)


def rebase(s: pd.Series, base_start: pd.Timestamp, base_end: pd.Timestamp, min_obs: int = 3) -> pd.Series | None:
    """The series indexed to 100 = its own mean over the baseline months, or None with fewer than ``min_obs``
    baseline observations. Indexing a series to itself never mixes units or bases."""
    s = as_monthly(s)
    base = s[(s.index >= base_start) & (s.index <= base_end)].dropna()
    if len(base) < min_obs or base.mean() <= 0:
        return None
    return 100.0 * s / float(base.mean())


def find_base_breaks(
    levels: pd.Series, reference_periods: pd.Series, mom_threshold: float = BASE_BREAK_MOM
) -> list[pd.Timestamp]:
    """Months where an index changed its reference period **and** its level jumped discontinuously.

    ``levels`` and ``reference_periods`` share a month index. The IMF re-expresses an index on a new reference
    period when the national statistics office rebases it. Most rebased series are spliced so the level is
    continuous (a rebase is then harmless for ratios), but a series that is not spliced steps by a large factor at
    the junction (observed: Libya, January 2025, -67%). A reference-period change alone is not a break; a
    reference-period change with a one-month level move beyond ``mom_threshold`` is. A genuine inflation of that
    size in the very month of a rebase is not distinguishable, so the rule errs towards withholding the changes
    that span the break.
    """
    lv = as_monthly(levels)
    ref = reference_periods.copy()
    ref.index = ref.index.to_period("M").to_timestamp()
    ref = ref.reindex(lv.index)
    out: list[pd.Timestamp] = []
    prev: pd.Timestamp | None = None
    for t in lv.index:
        if prev is not None and (t.year * 12 + t.month) - (prev.year * 12 + prev.month) == 1:
            changed = pd.notna(ref[t]) and pd.notna(ref[prev]) and ref[t] != ref[prev]
            a, b = lv[prev], lv[t]
            if changed and pd.notna(a) and pd.notna(b) and a > 0 and abs(b / a - 1.0) > mom_threshold:
                out.append(t)
        prev = t
    return out


# --- exchange rates --------------------------------------------------------------------------------------------


def invert_quote(rate: pd.Series) -> pd.Series:
    """Domestic-per-USD to USD-per-domestic (``1 / rate``). Non-positive rates are invalid and become NaN."""
    r = as_monthly(rate)
    return 1.0 / r.where(r > 0)


def usd_value_change(local_per_usd_change: float) -> float:
    """The change in the USD value of one unit of domestic currency implied by a change ``x`` in domestic currency
    per USD: ``1 / (1 + x) - 1``. A 25% rise in units per dollar is a 20% fall in the currency's dollar value; the
    two are not the same number and the page always says which one it shows."""
    if local_per_usd_change <= -1.0:
        raise TransformError("a change of -100% or less is not a valid exchange-rate change")
    return 1.0 / (1.0 + local_per_usd_change) - 1.0


def fx_step_changes(rate: pd.Series, mom_threshold: float = FX_STEP_MOM) -> list[dict[str, Any]]:
    """One-month moves of at least ``mom_threshold`` (either direction) in a domestic-per-USD rate."""
    ch = mom_pct(rate)
    return [
        {"period": t.strftime("%Y-%m"), "mom_pct": float(v)}
        for t, v in ch.items()
        if pd.notna(v) and abs(v) >= mom_threshold
    ]


# --- combining nominal changes ---------------------------------------------------------------------------------


def real_change(nominal: float, deflator: float) -> float:
    """Change in the price **relative to** a deflator over the same period: ``(1 + nominal) / (1 + deflator) - 1``.

    The deflator is named wherever this is shown (headline CPI or food CPI). It is a relative-price statement about
    the national average basket, not about any household's purchasing power, and not a causal share.
    """
    if deflator <= -1.0:
        raise TransformError("a deflator change of -100% or less is not valid")
    return (1.0 + nominal) / (1.0 + deflator) - 1.0


def log_share(part: float, whole: float, min_abs_log: float = 0.02) -> float | None:
    """``ln(1 + part) / ln(1 + whole)``: the share of a log change accounted for by another log change.

    Returned only when the whole is large enough for a share to be meaningful (|ln(1 + whole)| >= ``min_abs_log``,
    about 2%). This is arithmetic on two numbers, not an estimate of how much of one *caused* the other.
    """
    if part <= -1.0 or whole <= -1.0:
        return None
    w = math.log1p(whole)
    if abs(w) < min_abs_log:
        return None
    return math.log1p(part) / w


def decompose_log_change(usd_change: float, fx_change: float) -> dict[str, float]:
    """A benchmark's change in local currency decomposes exactly: ``ln(P_usd * fx)`` = ``ln(P_usd) + ln(fx)``.

    ``usd_change`` is the benchmark's USD change and ``fx_change`` the change in domestic currency per USD over the
    same months. The identity is arithmetic; it says how the local-currency change splits between the two
    ingredients, not why either moved.
    """
    if usd_change <= -1.0 or fx_change <= -1.0:
        raise TransformError("changes of -100% or less are not valid")
    usd_log, fx_log = math.log1p(usd_change), math.log1p(fx_change)
    return {
        "usd_benchmark_log": usd_log,
        "exchange_rate_log": fx_log,
        "local_currency_log": usd_log + fx_log,
        "local_currency_change": math.expm1(usd_log + fx_log),
    }


def to_usd(price_local: pd.Series, local_per_usd: pd.Series) -> pd.Series:
    """Local price divided by domestic currency per USD, month by month where both exist (an indicative USD value at
    the **official period-average** rate, which may differ from the rate households actually faced)."""
    p, r = as_monthly(price_local), as_monthly(local_per_usd)
    return p / r.where(r > 0)


# --- descriptive lagged comparison -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LagRow:
    lag: int
    n: int
    spearman: float | None
    status: str  # "ok" | "insufficient" (too few paired months) | "no_variation" (too few distinct values)


def log_monthly_changes(s: pd.Series, breaks: list[pd.Timestamp] | None = None) -> pd.Series:
    """One-month log changes ``ln(s_t / s_{t-1})`` (non-overlapping, so lagged comparisons do not reuse months)."""
    m = mom_pct(s, breaks)
    return np.log1p(m.where(m > -1.0))


def _by_month_number(s: pd.Series) -> pd.Series:
    return pd.Series(s.to_numpy(), index=pd.Index(s.index.year * 12 + s.index.month - 1))


def lagged_comparison(
    local: pd.Series, reference: pd.Series, lags: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6), min_obs: int = MIN_LAG_OBS
) -> list[LagRow]:
    """Spearman rank correlation between the local series' monthly log changes at month ``t`` and the reference
    series' monthly log changes at month ``t - lag`` (the reference leads by ``lag`` months).

    **Descriptive only.** Monthly changes are used because 12-month changes overlap and would make neighbouring
    values nearly identical. No p-value or confidence interval is produced: the observations are autocorrelated,
    seven lags are looked at, and nothing about timing identifies a mechanism. All lags are returned, never only
    the largest, and a lag with fewer than ``min_obs`` paired months is ``insufficient``, not zero.
    """
    # Months are shifted as integers (year * 12 + month): the same alignment as shifting a month-start index, without
    # constructing a date range for every lag, which dominated the cost of an investigation.
    a = _by_month_number(as_monthly(local))
    b = _by_month_number(as_monthly(reference))
    rows: list[LagRow] = []
    for lag in lags:
        if lag < 0:
            raise TransformError("lags must be >= 0 (the reference leads the local series)")
        pair = pd.concat([a, pd.Series(b.to_numpy(), index=b.index + lag)], axis=1, join="inner").dropna()
        n = len(pair)
        if n < min_obs:
            rows.append(LagRow(lag, n, None, "insufficient"))
            continue
        if pair.iloc[:, 0].nunique() < 3 or pair.iloc[:, 1].nunique() < 3:
            rows.append(LagRow(lag, n, None, "no_variation"))  # e.g. an administered exchange rate that never moved
            continue
        rho = float(pair.iloc[:, 0].rank().corr(pair.iloc[:, 1].rank()))
        rows.append(LagRow(lag, n, rho if np.isfinite(rho) else None, "ok" if np.isfinite(rho) else "insufficient"))
    return rows


# --- information availability -----------------------------------------------------------------------------------


def available_as_of(s: pd.Series, release_lag_months: int, as_of: pd.Timestamp | None) -> pd.Series:
    """Keep only observations that could have been known at ``as_of`` under a publication-lag **assumption**.

    An observation for reference month ``p`` is assumed published ``release_lag_months`` months later (the month in
    which the lag ends). With ``as_of`` None nothing is removed: the series is the current archived vintage, which
    is for historical exploration and must not be read as what was visible at the time (statistical offices revise
    and re-base series). The lag is an assumption stated in the output, not a verified release date.
    """
    s = as_monthly(s)
    if as_of is None:
        return s
    cutoff = pd.Timestamp(as_of).to_period("M").to_timestamp() - pd.DateOffset(months=release_lag_months)
    return s[s.index <= cutoff]
