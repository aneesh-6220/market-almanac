"""Forecast evaluation metrics.

Metrics are suppressed (returned as None with a reason) when the sample cannot support
them, e.g. PR-AUC with too few positive events.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

DIRECTION_DEADBAND = 0.005  # ignore |actual log change| < 0.5% when scoring direction


def regression_metrics(
    y: np.ndarray,
    p: np.ndarray,
    naive_mae: float | None = None,
    naive_rmse: float | None = None,
    is_naive: bool = False,
) -> dict[str, Any]:
    e = p - y
    n = len(y)
    if n == 0:
        return {"n": 0}
    mae = float(np.mean(np.abs(e)))
    rmse = float(np.sqrt(np.mean(e**2)))
    out: dict[str, Any] = {"n": n, "mae": mae, "rmse": rmse, "bias": float(np.mean(e))}
    out["relative_mae"] = mae / naive_mae if naive_mae else None
    out["relative_rmse"] = rmse / naive_rmse if naive_rmse else None
    moving = np.abs(y) >= DIRECTION_DEADBAND
    if is_naive or moving.sum() < 10:
        out["directional_accuracy"] = None
        out["directional_note"] = "undefined for the naive forecast" if is_naive else "too few non-trivial moves"
    else:
        out["directional_accuracy"] = float(np.mean(np.sign(p[moving]) == np.sign(y[moving])))
        out["directional_n"] = int(moving.sum())
    return out


def classification_metrics(
    y: np.ndarray,
    p: np.ndarray,
    threshold: np.ndarray | float,
    base_rate_brier: float | None = None,
    min_events: int = 10,
) -> dict[str, Any]:
    n = len(y)
    if n == 0:
        return {"n": 0}
    y = y.astype(int)
    pos = int(y.sum())
    neg = n - pos
    brier = float(np.mean((p - y) ** 2))
    out: dict[str, Any] = {"n": n, "positives": pos, "event_rate": pos / n, "brier": brier}
    out["brier_skill"] = 1 - brier / base_rate_brier if base_rate_brier else None
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    out["log_loss"] = float(log_loss(y, pc, labels=[0, 1]))
    thr = np.broadcast_to(np.asarray(threshold, dtype=float), p.shape)
    pred = p >= thr
    tp = int(np.sum(pred & (y == 1)))
    fp = int(np.sum(pred & (y == 0)))
    fn = int(np.sum(~pred & (y == 1)))
    tn = int(np.sum(~pred & (y == 0)))
    out["confusion"] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn}
    if pos < min_events or neg < min_events:
        out.update(
            {
                "precision": None,
                "recall": None,
                "f1": None,
                "pr_auc": None,
                "roc_auc": None,
                "suppressed_reason": f"fewer than {min_events} positive or negative events in the test sample",
            }
        )
        return out
    out["precision"] = tp / (tp + fp) if (tp + fp) else None
    out["recall"] = tp / (tp + fn) if (tp + fn) else None
    out["f1"] = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    if np.unique(p).size > 1:
        out["pr_auc"] = float(average_precision_score(y, p))
        out["roc_auc"] = float(roc_auc_score(y, p))
    else:
        out["pr_auc"] = None
        out["roc_auc"] = None
        out["auc_note"] = "constant predictions: ranking metrics undefined"
    return out


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10, min_count: int = 10) -> list[dict[str, Any]]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < bins - 1 else (p <= hi))
        c = int(m.sum())
        out.append(
            {
                "bin_low": float(lo),
                "bin_high": float(hi),
                "count": c,
                "mean_predicted": float(p[m].mean()) if c else None,
                "observed_rate": float(y[m].mean()) if c >= min_count else None,
                "suppressed": c < min_count,
            }
        )
    return out
