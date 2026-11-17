"""Statistical comparison of forecasts under time dependence.

Rolling-origin forecasts are *not* independent: h-step forecasts overlap, errors are
autocorrelated, and different markets share common shocks in the same month. We therefore:

1. average the loss differential across series *within each origin month*, giving one
   time series d_t (absorbs contemporaneous cross-market correlation);
2. test E[d_t] = 0 with the Diebold–Mariano statistic using a Newey–West (Bartlett) HAC
   variance with at least h-1 lags, plus the Harvey–Leybourne–Newbold small-sample
   correction and Student-t reference distribution;
3. form confidence intervals with a moving-block bootstrap over origin months, on the same
   equally weighted monthly-mean estimand the test uses;
4. adjust families of pre-specified tests with Holm's step-down procedure.
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
    weighting: str = "months",
) -> dict[str, float | int | str | None]:
    """Percentile CI for a loss ratio B/A, resampling moving blocks of origin months.

    ``weighting="months"`` (default): ratio of the *equally weighted monthly mean* losses,
    mean_t(mean_i loss_b) / mean_t(mean_i loss_a). This is the estimand whose difference the
    Diebold-Mariano test examines, so interval and test refer to the same quantity.

    ``weighting="rows"``: ratio of row-summed losses, sum(loss_b) / sum(loss_a), which gives
    months with more reporting markets more weight (the v0.1 definition; kept for comparison).
    """
    if weighting not in ("months", "rows"):
        raise ValueError("weighting must be 'months' or 'rows'")
    df = pd.DataFrame({"a": np.asarray(loss_a), "b": np.asarray(loss_b), "date": np.asarray(dates)})
    g = df.groupby("date")[["a", "b"]].agg("mean" if weighting == "months" else "sum").sort_index()
    sa = g["a"].to_numpy()
    sb = g["b"].to_numpy()
    T = len(sa)
    if T < 12 or sa.sum() == 0:
        return {"ratio": None, "ci_low": None, "ci_high": None, "block_length": None, "reps": 0, "weighting": weighting}
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
    point = float(sb.sum() / sa.sum())
    if len(ratios) < reps // 2:
        return {"ratio": point, "ci_low": None, "ci_high": None, "block_length": L, "reps": 0, "weighting": weighting}
    return {
        "ratio": point,
        "ci_low": float(np.quantile(ratios, alpha / 2)),
        "ci_high": float(np.quantile(ratios, 1 - alpha / 2)),
        "block_length": L,
        "reps": len(ratios),
        "weighting": weighting,
    }


def holm_adjust(p_values: list[float | None]) -> list[float | None]:
    """Holm (1979) step-down adjusted p-values controlling the family-wise error rate.

    Sort p_(1) <= ... <= p_(m); adjusted p_(i) = max_{j<=i} min(1, (m - j + 1) * p_(j)).
    ``None`` entries (tests that could not be computed) are excluded from the family and
    returned as ``None``.
    """
    idx = [i for i, p in enumerate(p_values) if p is not None and np.isfinite(p)]
    out: list[float | None] = [None] * len(p_values)
    m = len(idx)
    running = 0.0
    for rank, i in enumerate(sorted(idx, key=lambda k: p_values[k])):  # type: ignore[arg-type, return-value]
        running = max(running, min(1.0, (m - rank) * float(p_values[i])))  # type: ignore[arg-type]
        out[i] = running
    return out
