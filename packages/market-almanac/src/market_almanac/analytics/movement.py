"""How unusual is a price movement? A documented, deterministic historical comparison.

For one comparable series with monthly prices P, let the change ending in month T over a span
of k months be

    r_T(k) = ln P_T - ln P_{T-k}

(k = 1 when the previous month was observed; if months are missing, k is the distance to the
last observed month, so a change is never computed across an unacknowledged gap).

Reference set. Only changes of the same span that ended *before* T are used:
``R = { r_s(k) : s < T }``. The assessment therefore never uses later data and can be recomputed
for any past month.

* **Percentile of size**: the share of |r| in R strictly smaller than |r_T|. "Larger than 96% of
  earlier one-month moves."
* **Robust z-score**: (r_T - median(R)) / (1.4826 x MAD(R)), with a floor on the scale so a
  near-constant history cannot produce an arbitrarily large score.
* **Seasonal reference**: the same statistics against changes that ended in the same calendar
  month in earlier years, when at least ``MIN_SEASONAL`` exist.

Labels (by percentile of size): below 0.80 *typical*; 0.80-0.95 *larger than usual*; 0.95-0.99
*unusual*; 0.99 and above *exceptional*. With fewer than ``MIN_HISTORY`` reference changes no
label is given; between ``MIN_HISTORY`` and ``STABLE_HISTORY`` the label is marked unstable.

A label describes the statistics of one price series. It is not a finding of a shortage, a
supply failure or a crisis, and it says nothing about causes.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MIN_HISTORY = 24
STABLE_HISTORY = 48
MIN_SEASONAL = 5
MAX_GAP_SPAN = 6
SCALE_FLOOR = 0.01  # log points
LABELS = ((0.99, "exceptional"), (0.95, "unusual"), (0.80, "larger_than_usual"), (0.0, "typical"))
METHOD = (
    "Log price change compared with earlier changes of the same span in the same series: percentile of absolute "
    "size and robust z-score (median / MAD); seasonal reference = changes ending in the same calendar month."
)


def log_changes(price: pd.Series, span: int = 1) -> pd.Series:
    """ln P_t - ln P_{t-span} on a complete monthly index (NaN wherever either price is missing)."""
    p = price.where(price > 0)
    full = p.reindex(pd.date_range(p.index.min(), p.index.max(), freq="MS")) if len(p) else p
    lp = np.log(full)
    return lp - lp.shift(span)


def label_for(percentile: float | None, n_ref: int) -> str:
    if percentile is None or n_ref < MIN_HISTORY:
        return "insufficient_history"
    return next(name for cut, name in LABELS if percentile >= cut)


def _robust_z(x: float, ref: np.ndarray) -> float | None:
    if len(ref) < MIN_SEASONAL:
        return None
    med = float(np.median(ref))
    mad = float(np.median(np.abs(ref - med)))
    return (x - med) / max(1.4826 * mad, SCALE_FLOOR)


def _against(x: float, ref: np.ndarray) -> dict[str, Any]:
    n = len(ref)
    pct = float(np.mean(np.abs(ref) < abs(x))) if n else None
    return {
        "n_reference": n,
        "percentile_of_size": pct,
        "robust_z": _robust_z(x, ref),
        "reference_median": float(np.median(ref)) if n else None,
        "reference_p10": float(np.quantile(ref, 0.10)) if n else None,
        "reference_p90": float(np.quantile(ref, 0.90)) if n else None,
    }


def assess_movement(price: pd.Series, at: pd.Timestamp | None = None) -> dict[str, Any]:
    """Assess the change ending at month ``at`` (default: the latest observed month)."""
    p = price.where(price > 0).dropna().sort_index()
    if at is not None:
        p = p[p.index <= pd.Timestamp(at)]
    if len(p) < 2:
        return {"status": "insufficient_history", "label": "insufficient_history", "method": METHOD}
    t, prev = p.index[-1], p.index[-2]
    span = (t.year - prev.year) * 12 + (t.month - prev.month)
    out: dict[str, Any] = {
        "status": "ok",
        "method": METHOD,
        "period": t.date().isoformat(),
        "reference_period": prev.date().isoformat(),
        "span_months": span,
        "price": float(p.iloc[-1]),
        "reference_price": float(p.iloc[-2]),
        "log_change": float(np.log(p.iloc[-1] / p.iloc[-2])),
        "pct_change": float(p.iloc[-1] / p.iloc[-2] - 1),
        "direction": "up" if p.iloc[-1] > p.iloc[-2] else "down" if p.iloc[-1] < p.iloc[-2] else "flat",
        "spans_gap": span > 1,
        "warnings": [],
    }
    if span > MAX_GAP_SPAN:
        out.update({"status": "gap_too_long", "label": "insufficient_history"})
        out["warnings"].append(f"the previous observation is {span} months earlier; no comparison is made")
        return out
    changes = log_changes(p, span)
    ref = changes[changes.index < t].dropna()
    r = out["log_change"]
    out["overall"] = _against(r, ref.to_numpy())
    seasonal = ref[ref.index.month == t.month]
    out["seasonal"] = (
        {**_against(r, seasonal.to_numpy()), "calendar_month": int(t.month)} if len(seasonal) >= MIN_SEASONAL else None
    )
    n = out["overall"]["n_reference"]
    out["label"] = label_for(out["overall"]["percentile_of_size"], n)
    out["stable"] = n >= STABLE_HISTORY
    if span > 1:
        out["warnings"].append(
            f"the change spans {span} months because intermediate months are missing; it is compared with earlier "
            f"{span}-month changes"
        )
    if n < MIN_HISTORY:
        out["warnings"].append(f"only {n} earlier comparable changes (at least {MIN_HISTORY} are needed for a label)")
    elif n < STABLE_HISTORY:
        out["warnings"].append(f"only {n} earlier comparable changes; the label may be unstable")
    # 12-month change against earlier 12-month changes
    yoy = log_changes(p, 12)
    if t in yoy.index and np.isfinite(yoy[t]):
        yref = yoy[yoy.index < t].dropna().to_numpy()
        out["year_on_year"] = {
            "log_change": float(yoy[t]),
            "pct_change": float(np.exp(yoy[t]) - 1),
            **_against(float(yoy[t]), yref),
        }
        out["year_on_year"]["label"] = label_for(out["year_on_year"]["percentile_of_size"], len(yref))
    else:
        out["year_on_year"] = None
    out["volatility"] = volatility(p, t)
    return out


def volatility(price: pd.Series, at: pd.Timestamp, window: int = 6) -> dict[str, Any] | None:
    """Standard deviation of the last ``window`` monthly log changes versus its own earlier values."""
    d = log_changes(price, 1)
    roll = d.rolling(window, min_periods=window - 1).std()
    if at not in roll.index or not np.isfinite(roll[at]):
        return None
    ref = roll[roll.index < at].dropna().to_numpy()
    cur = float(roll[at])
    pct = float(np.mean(ref < cur)) if len(ref) else None
    return {
        "window_months": window,
        "sd_log_change": cur,
        "n_reference": len(ref),
        "percentile": pct,
        "label": "insufficient_history"
        if len(ref) < MIN_HISTORY
        else "elevated"
        if pct is not None and pct >= 0.90
        else "typical",
    }


def movement_history(price: pd.Series, min_percentile: float = 0.95) -> list[dict[str, Any]]:
    """Every past month whose one-month change was unusual *given the history available then*."""
    p = price.where(price > 0).dropna().sort_index()
    d = log_changes(p, 1).dropna()
    vals, idx = d.to_numpy(), d.index
    out = []
    for i in range(MIN_HISTORY, len(vals)):
        ref = vals[:i]
        pct = float(np.mean(np.abs(ref) < abs(vals[i])))
        if pct >= min_percentile:
            out.append(
                {
                    "period": idx[i].date().isoformat(),
                    "log_change": float(vals[i]),
                    "pct_change": float(np.exp(vals[i]) - 1),
                    "percentile_of_size": pct,
                    "label": label_for(pct, i),
                    "n_reference": i,
                }
            )
    return out


def peer_context(panel: pd.DataFrame, series_id: str, period: pd.Timestamp) -> dict[str, Any] | None:
    """Did other markets for the same commodity and country move the same way in that month?

    ``panel``: monthly prices, index = month, one column per series of the same country,
    commodity, unit, price type and currency. A move shared by many markets is unlikely to be a
    single-market reporting error; an isolated move that reverses next month may be one.
    """
    if series_id not in panel.columns or period not in panel.index:
        return None
    d = np.log(panel.where(panel > 0)).diff()
    row = d.loc[period].dropna()
    own = row.get(series_id)
    peers = row.drop(labels=[series_id], errors="ignore")
    if own is None or not np.isfinite(own) or len(peers) < 3:
        return {"n_peers": len(peers), "status": "too_few_peers"}
    same = float(np.mean(np.sign(peers) == np.sign(own)))
    nxt = period + pd.DateOffset(months=1)
    reverses = None
    if nxt in d.index and np.isfinite(d.loc[nxt].get(series_id, np.nan)):
        back = float(d.loc[nxt, series_id])
        reverses = bool(np.sign(back) == -np.sign(own) and abs(back) >= 0.8 * abs(own))
    if same >= 0.6 and abs(float(peers.median())) >= 0.25 * abs(own):
        pattern = "shared"  # most peer markets moved the same way: consistent with a market-wide movement
    elif reverses:
        pattern = "isolated_reversing"  # candidate reporting or measurement anomaly
    elif same < 0.4:
        pattern = "isolated"
    else:
        pattern = "mixed"
    return {
        "status": "ok",
        "n_peers": len(peers),
        "peer_median_log_change": float(peers.median()),
        "peer_median_pct_change": float(np.exp(peers.median()) - 1),
        "share_same_direction": same,
        "reverses_next_month": reverses,
        "pattern": pattern,
    }
