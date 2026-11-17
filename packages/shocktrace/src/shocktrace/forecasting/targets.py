"""Forecast targets.

For a comparable price series P (one series_id) and forecast origin t (a month):

* Task A – log change over horizon h:      y_t(h) = ln P_{t+h} - ln P_t
* Task B – spike event at threshold c:      s_t(h) = 1[ P_{t+h} / P_t - 1 >= c ]

If P_t or P_{t+h} is missing the target is *missing* (NaN) — it is never treated as
"no change" or "no spike".
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def log_change_target(price: pd.Series, h: int) -> pd.Series:
    """price indexed by consecutive months (missing months present as NaN)."""
    if h < 1:
        raise ValueError("horizon must be >= 1")
    lp = np.log(price.where(price > 0))
    return lp.shift(-h) - lp


def spike_target(price: pd.Series, h: int, threshold: float) -> pd.Series:
    if not 0 < threshold < 5:
        raise ValueError("spike threshold must be a positive fraction, e.g. 0.10 for +10%")
    p = price.where(price > 0)
    pct = p.shift(-h) / p - 1.0
    out = pd.Series(np.where(pct >= threshold, 1.0, 0.0), index=price.index)
    out[pct.isna()] = np.nan
    return out


def pct_change(p0: float, p1: float) -> float:
    return p1 / p0 - 1.0


def log_change(p0: float, p1: float) -> float:
    return float(np.log(p1) - np.log(p0))
