"""Forecast targets under an explicit price-availability assumption.

Notation. ``t`` is the *forecast origin*: the month at whose end the forecast is made. ``L`` is
the assumed price release lag in months, so the latest price a forecaster holds at ``t`` is
``P_{t-L}`` (the *reference price*). ``h`` is the horizon counted from the origin.

* Task A - log change:   y_t(h) = ln P_{t+h} - ln P_{t-L}
* Task B - spike event:  s_t(h) = 1[ P_{t+h} / P_{t-L} - 1 >= c ]

With ``L = 0`` these reduce to the usual ``ln P_{t+h} - ln P_t``. With ``L > 0`` the change is
measured from the last price assumed published, so no target depends on a reference price the
forecaster could not have seen; the span between the two prices is ``h + L`` months.

If either price is missing the target is *missing* (NaN) - it is never treated as "no change"
or "no spike".
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _check(h: int, lag: int) -> None:
    if h < 1:
        raise ValueError("horizon must be >= 1")
    if lag < 0:
        raise ValueError("price release lag must be >= 0")


def log_change_target(price: pd.Series, h: int, lag: int = 0) -> pd.Series:
    """price indexed by consecutive months (missing months present as NaN)."""
    _check(h, lag)
    lp = np.log(price.where(price > 0))
    return lp.shift(-h) - lp.shift(lag)


def spike_target(price: pd.Series, h: int, threshold: float, lag: int = 0) -> pd.Series:
    _check(h, lag)
    if not 0 < threshold < 5:
        raise ValueError("spike threshold must be a positive fraction, e.g. 0.10 for +10%")
    p = price.where(price > 0)
    pct = p.shift(-h) / p.shift(lag) - 1.0
    out = pd.Series(np.where(pct >= threshold, 1.0, 0.0), index=price.index)
    out[pct.isna()] = np.nan
    return out


def pct_change(p0: float, p1: float) -> float:
    return p1 / p0 - 1.0


def log_change(p0: float, p1: float) -> float:
    return float(np.log(p1) - np.log(p0))
