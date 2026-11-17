"""Statistical comparison of forecasts under time dependence.

Rolling-origin forecasts are *not* independent: h-step forecasts overlap, errors are
autocorrelated, and different markets share common shocks in the same month. We therefore:

1. average the loss differential across series *within each origin month*, giving one
   time series d_t (absorbs contemporaneous cross-market correlation);
2. test E[d_t] = 0 with the Diebold–Mariano statistic using a Newey–West (Bartlett) HAC
   variance with at least h-1 lags, plus the Harvey–Leybourne–Newbold small-sample
   correction and Student-t reference distribution;
3. form confidence intervals with a moving-block bootstrap over origin months.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class DMResult:
    n_periods: int
    mean_diff: float
    stat: float | None
    p_value_two_sided: float | None
    p_value_b_better: float | None  # one-sided: H1 loss_B < loss_A
    lags: int
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def newey_west_variance(d: np.ndarray, lags: int) -> float:
    d = d - d.mean()
    T = len(d)
    gamma0 = float(np.dot(d, d) / T)
    v = gamma0
    for k in range(1, lags + 1):
        if k >= T:
            break
        w = 1 - k / (lags + 1)
        v += 2 * w * float(np.dot(d[k:], d[:-k]) / T)
    return v


def diebold_mariano(loss_a: pd.Series, loss_b: pd.Series, dates: pd.Series, h: int, min_periods: int = 24) -> DMResult:
    """d_t = mean_i(loss_a - loss_b) per date. Positive mean => B has lower loss."""
    df = pd.DataFrame({"d": np.asarray(loss_a) - np.asarray(loss_b), "date": np.asarray(dates)})
    d = df.groupby("date")["d"].mean().sort_index().to_numpy()
    T = len(d)
    lags = max(h - 1, math.floor(4 * (T / 100) ** (2 / 9))) if T else 0
    if min_periods > T:
        return DMResult(
            T,
            float(d.mean()) if T else float("nan"),
            None,
            None,
            None,
            lags,
            f"insufficient evaluation periods ({T} < {min_periods})",
        )
    var = newey_west_variance(d, lags)
    if var <= 0 or not np.isfinite(var):
        return DMResult(T, float(d.mean()), None, None, None, lags, "non-positive HAC variance")
    dm = float(d.mean() / math.sqrt(var / T))
    hln = math.sqrt(max((T + 1 - 2 * h + h * (h - 1) / T) / T, 1e-12))
    stat = dm * hln
    p2 = float(2 * stats.t.sf(abs(stat), df=T - 1))
    p1 = float(stats.t.sf(stat, df=T - 1))
    return DMResult(T, float(d.mean()), stat, p2, p1, lags)


def moving_block_bootstrap_ratio(
    loss_a: pd.Series,
    loss_b: pd.Series,
    dates: pd.Series,
    h: int,
    reps: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float | int | None]:
    """CI for the ratio sum(loss_b)/sum(loss_a) resampling blocks of origin months."""
    df = pd.DataFrame({"a": np.asarray(loss_a), "b": np.asarray(loss_b), "date": np.asarray(dates)})
    g = df.groupby("date")[["a", "b"]].agg(["sum", "count"]).sort_index()
    sa = g[("a", "sum")].to_numpy()
    sb = g[("b", "sum")].to_numpy()
    T = len(sa)
    if T < 12 or sa.sum() == 0:
        return {"ratio": None, "ci_low": None, "ci_high": None, "block_length": None, "reps": 0}
    L = max(h, round(T ** (1 / 3)))
    rng = np.random.default_rng(seed)
    nblocks = math.ceil(T / L)
    ratios = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, T - L + 1, nblocks)
        idx = (starts[:, None] + np.arange(L)).ravel()[:T]
        denom = sa[idx].sum()
        ratios[r] = sb[idx].sum() / denom if denom > 0 else np.nan
    ratios = ratios[np.isfinite(ratios)]
    if len(ratios) < reps // 2:
        return {"ratio": float(sb.sum() / sa.sum()), "ci_low": None, "ci_high": None, "block_length": L, "reps": 0}
    return {
        "ratio": float(sb.sum() / sa.sum()),
        "ci_low": float(np.quantile(ratios, alpha / 2)),
        "ci_high": float(np.quantile(ratios, 1 - alpha / 2)),
        "block_length": L,
        "reps": len(ratios),
    }
