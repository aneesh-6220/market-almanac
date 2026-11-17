"""Market comparison: only series that measure the same thing are compared.

Two price series are *comparable in level* when they share commodity, price type (retail or
wholesale), unit and currency. Series that differ only in currency can still be compared in
*relative* terms (each indexed to its own base month), because an index removes the unit of
account; that is never a cost-of-living comparison. Series that differ in commodity, unit or
price type are not compared at all.

Market Almanac does not convert currencies: it holds no verified, date-matched exchange-rate series
for every currency pair, and a nominal conversion would not make prices comparable in
purchasing-power terms anyway.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MAX_SERIES = 8
MIN_OVERLAP_FOR_CORRELATION = 24
IDENTITY_FIELDS = ("commodity_name", "price_type", "unit")


def _norm(v: Any) -> str:
    return str(v).strip().lower()


def assess_comparability(meta: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide what kind of comparison a set of series supports, with the reasons."""
    if len(meta) < 2:
        return {"level": "single", "absolute": False, "indexed": False, "reasons": ["select at least two series"]}
    if len(meta) > MAX_SERIES:
        return {
            "level": "invalid",
            "absolute": False,
            "indexed": False,
            "reasons": [f"at most {MAX_SERIES} series can be compared at once"],
        }
    reasons: list[str] = []
    blocking: list[str] = []
    for f in IDENTITY_FIELDS:
        vals = sorted({_norm(m[f]) for m in meta})
        if len(vals) > 1:
            blocking.append(f"{f.replace('_', ' ')} differs ({', '.join(vals)})")
    if blocking:
        return {
            "level": "invalid",
            "absolute": False,
            "indexed": False,
            "reasons": [*blocking, "series that measure different things are not compared"],
        }
    currencies = sorted({str(m["currency"]) for m in meta})
    countries = sorted({str(m["country_iso3"]) for m in meta})
    flags = sorted({str(m.get("price_flag", "actual")) for m in meta})
    absolute = len(currencies) == 1
    if not absolute:
        reasons.append(
            f"currencies differ ({', '.join(currencies)}): price levels are not comparable and no conversion is "
            "applied; only indexed (relative) movements are shown"
        )
    if len(countries) > 1:
        reasons.append(
            "markets are in different countries: commodity definitions, varieties and quality grades may differ "
            "even under the same name"
        )
        if absolute:
            reasons.append("a shared currency does not make prices a cost-of-living comparison")
    if len(flags) > 1 or flags != ["actual"]:
        reasons.append(f"price flags differ or include non-actual values ({', '.join(flags)})")
    return {
        "level": "absolute_and_indexed" if absolute else "indexed_only",
        "absolute": absolute,
        "indexed": True,
        "currencies": currencies,
        "countries": countries,
        "reasons": reasons,
    }


def align(
    series: dict[str, pd.Series], start: pd.Timestamp | None = None, end: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Outer-join monthly series on a complete month index; missing observations stay missing."""
    clean = {k: v.where(v > 0).dropna().sort_index() for k, v in series.items()}
    clean = {k: v for k, v in clean.items() if len(v)}
    if not clean:
        return pd.DataFrame()
    lo = min(v.index.min() for v in clean.values())
    hi = max(v.index.max() for v in clean.values())
    lo = max(lo, start) if start is not None else lo
    hi = min(hi, end) if end is not None else hi
    if lo > hi:
        return pd.DataFrame(columns=list(series))
    idx = pd.date_range(lo, hi, freq="MS")
    return pd.DataFrame({k: v.reindex(idx) for k, v in clean.items()}, index=idx)


def index_series(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Index every series to 100 at a base month.

    The base is the first month in which *all* series are observed. If no such month exists each
    series is indexed to its own first observation and the result is flagged, because the
    indices then do not share a starting point.
    """
    if frame.empty:
        return frame, {"mode": "none", "base_period": None}
    common = frame.dropna(how="any")
    if len(common):
        base = common.index[0]
        return frame / frame.loc[base] * 100.0, {"mode": "common_base", "base_period": base.date().isoformat()}
    firsts = {c: frame[c].first_valid_index() for c in frame.columns}
    out = pd.DataFrame({c: frame[c] / frame.loc[firsts[c], c] * 100.0 for c in frame.columns if firsts[c] is not None})
    return out, {
        "mode": "own_first_observation",
        "base_period": None,
        "warning": "no month has observations for every series; each is indexed to its own first observation",
        "base_periods": {c: (None if f is None else f.date().isoformat()) for c, f in firsts.items()},
    }


def compare(
    series: dict[str, pd.Series],
    meta: list[dict[str, Any]],
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> dict[str, Any]:
    comp = assess_comparability(meta)
    if comp["level"] in ("single", "invalid"):
        return {"comparability": comp, "status": "not_comparable", "series": [], "rows": []}
    frame = align(series, start, end)
    if frame.empty:
        return {"comparability": comp, "status": "no_overlapping_data", "series": [], "rows": []}
    idx, base = index_series(frame)
    months = len(frame)
    stats = []
    for sid in frame.columns:
        v = frame[sid].dropna()
        stats.append(
            {
                "series_id": sid,
                "n_observations": len(v),
                "missing_share": float(1 - len(v) / months),
                "first_period": v.index[0].date().isoformat(),
                "last_period": v.index[-1].date().isoformat(),
                "first_price": float(v.iloc[0]),
                "last_price": float(v.iloc[-1]),
                "pct_change_over_window": float(v.iloc[-1] / v.iloc[0] - 1),
                "window_months": (v.index[-1].year - v.index[0].year) * 12 + v.index[-1].month - v.index[0].month,
                "last_index": None
                if sid not in idx or not np.isfinite(idx[sid].dropna().iloc[-1])
                else float(idx[sid].dropna().iloc[-1]),
            }
        )
    last_common = frame.dropna(how="any")
    spread = None
    if comp["absolute"] and len(last_common):
        row = last_common.iloc[-1]
        spread = {
            "period": last_common.index[-1].date().isoformat(),
            "min": float(row.min()),
            "max": float(row.max()),
            "max_over_min": float(row.max() / row.min()),
            "lowest_series": str(row.idxmin()),
            "highest_series": str(row.idxmax()),
        }
    d = np.log(frame).diff()
    pairs = []
    cols = list(frame.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            j = d[[a, b]].dropna()
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "n": len(j),
                    "correlation_of_monthly_changes": float(j[a].corr(j[b]))
                    if len(j) >= MIN_OVERLAP_FOR_CORRELATION
                    else None,
                }
            )
    rows = [
        {
            "period": t.date().isoformat(),
            "prices": {c: (None if not np.isfinite(frame.loc[t, c]) else float(frame.loc[t, c])) for c in cols},
            "index": {
                c: (None if c not in idx or not np.isfinite(idx.loc[t, c]) else float(idx.loc[t, c])) for c in cols
            },
        }
        for t in frame.index
    ]
    return {
        "status": "ok",
        "comparability": comp,
        "window": {
            "start": frame.index[0].date().isoformat(),
            "end": frame.index[-1].date().isoformat(),
            "months": months,
        },
        "months_all_observed": len(last_common),
        "index_base": base,
        "series": stats,
        "latest_common_spread": spread,
        "pairs": pairs,
        "rows": rows,
        "caveats": [
            "Nominal prices. No inflation adjustment and no currency conversion is applied.",
            "Correlations of monthly changes are descriptive; they do not measure market integration causally.",
        ],
    }
