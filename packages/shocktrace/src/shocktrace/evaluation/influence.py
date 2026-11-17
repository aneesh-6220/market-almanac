"""Influence diagnostics for a forecast comparison.

A headline loss ratio is only trustworthy if it is not produced by a handful of observations.
For a comparison of model B against model A on matched rows this module reports how the ratio

    R = mean(loss_B) / mean(loss_A)            (row-weighted, the headline definition)

moves when parts of the evaluation sample are removed:

* each origin month (leave-one-month-out) and the three most influential months together;
* each market / price series (leave-one-series-out);
* each weather grid cell (leave-one-cell-out), when rows carry a ``location_id``;
* rows whose weather inputs carry a precipitation QC flag.

Nothing is dropped from the primary result. These are sensitivity analyses that tell a reader
whether the primary number depends on one month, one market, one cell or one data anomaly.

Fragility rule (fixed in advance, not tuned): a comparison is ``fragile`` when removing the
three most influential months, or any single series, or any single cell, shifts R by more than
``max(FRAGILE_ABS_SHIFT, FRAGILE_REL_SHIFT * |R - 1|)``, i.e. by more than two points of loss
ratio and more than half of the apparent effect.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FRAGILE_ABS_SHIFT = 0.02
FRAGILE_REL_SHIFT = 0.5
TOP_K_MONTHS = 3


def _loo(sum_a: np.ndarray, sum_b: np.ndarray) -> np.ndarray:
    """Leave-one-group-out ratios from per-group loss sums (count cancels in the ratio of means)."""
    ta, tb = sum_a.sum(), sum_b.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (tb - sum_b) / (ta - sum_a)
    return np.where(np.isfinite(r), r, np.nan)


def _group_block(df: pd.DataFrame, key: str, ratio: float, label_fmt: Any = str) -> dict[str, Any] | None:
    g = df.groupby(key)[["la", "lb"]].sum()
    if len(g) < 2:
        return None
    loo = _loo(g["la"].to_numpy(), g["lb"].to_numpy())
    shift = loo - ratio
    if not np.isfinite(shift).any():
        return None
    k = int(np.nanargmax(np.abs(shift)))
    return {
        "n_groups": len(g),
        "ratio_min": float(np.nanmin(loo)),
        "ratio_max": float(np.nanmax(loo)),
        "max_abs_shift": float(abs(shift[k])),
        "most_influential": label_fmt(g.index[k]),
        "ratio_without_most_influential": float(loo[k]),
    }


def influence_report(rows: pd.DataFrame) -> dict[str, Any]:
    """Influence diagnostics for matched comparison rows.

    ``rows`` columns: ``origin`` (month), ``series_id``, ``la``, ``lb`` (per-row losses of A and B)
    and optionally ``location_id`` and ``qc_flag`` (1 when the row's weather inputs were QC-flagged).
    """
    df = rows.dropna(subset=["la", "lb"])
    ta, tb = float(df["la"].sum()), float(df["lb"].sum())
    if df.empty or ta <= 0:
        return {"status": "insufficient_evidence"}
    ratio = tb / ta
    threshold = max(FRAGILE_ABS_SHIFT, FRAGILE_REL_SHIFT * abs(ratio - 1))
    out: dict[str, Any] = {"status": "ok", "ratio": ratio, "fragility_threshold": threshold}

    month = df.groupby("origin")[["la", "lb"]].sum().sort_index()
    excess = month["lb"] - month["la"]  # positive: B worse in that month
    loo = pd.Series(_loo(month["la"].to_numpy(), month["lb"].to_numpy()), index=month.index)
    order = (loo - ratio).abs().sort_values(ascending=False).index[:TOP_K_MONTHS]
    rest = month.drop(index=order)
    ratio_excl = float(rest["lb"].sum() / rest["la"].sum()) if rest["la"].sum() > 0 else None
    total_excess = float(excess.sum())
    out["months"] = {
        "n_months": len(month),
        "top": [
            {
                "origin": pd.Timestamp(o).date().isoformat(),
                "ratio_without": float(loo[o]),
                "shift": float(loo[o] - ratio),
                "share_of_excess_loss": float(excess[o] / total_excess) if total_excess != 0 else None,
            }
            for o in order
        ],
        "top_k": len(order),
        "ratio_without_top_k": ratio_excl,
        "shift_without_top_k": None if ratio_excl is None else float(ratio_excl - ratio),
        "top_k_share_of_excess_loss": float(excess[order].sum() / total_excess) if total_excess != 0 else None,
        "max_single_month_shift": float((loo - ratio).abs().max()),
    }
    out["series"] = _group_block(df, "series_id", ratio)
    out["cells"] = (
        _group_block(df.dropna(subset=["location_id"]), "location_id", ratio) if "location_id" in df else None
    )
    if "qc_flag" in df and df["qc_flag"].fillna(0).sum() > 0:
        clean = df[df["qc_flag"].fillna(0) == 0]
        out["qc_flagged_rows"] = {
            "n_flagged": int((df["qc_flag"].fillna(0) > 0).sum()),
            "ratio_excluding_flagged": float(clean["lb"].sum() / clean["la"].sum()) if clean["la"].sum() > 0 else None,
        }
    else:
        out["qc_flagged_rows"] = {"n_flagged": 0, "ratio_excluding_flagged": None}

    reasons: list[str] = []
    s = out["months"]["shift_without_top_k"]
    if s is not None and abs(s) > threshold:
        reasons.append(
            f"removing the {len(order)} most influential origin months moves the ratio "
            f"from {ratio:.3f} to {ratio_excl:.3f}"
        )
    for name, label in (("series", "price series"), ("cells", "weather cell")):
        b = out.get(name)
        if b and b["max_abs_shift"] > threshold:
            reasons.append(
                f"removing one {label} ({b['most_influential']}) moves the ratio "
                f"to {b['ratio_without_most_influential']:.3f}"
            )
    q = out["qc_flagged_rows"]["ratio_excluding_flagged"]
    if q is not None and abs(q - ratio) > threshold:
        reasons.append(f"excluding QC-flagged weather rows moves the ratio to {q:.3f}")
    out["fragile"] = bool(reasons)
    out["reasons"] = reasons
    return out
