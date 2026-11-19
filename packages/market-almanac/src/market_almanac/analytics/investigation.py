"""One price-shock investigation: a reproducible, bounded analysis of one series around one month.

Inputs are plain data (the series' monthly prices and stored records, its peers, other foods in the same
market, and whatever context is integrated for the country); the output is a JSON-safe document that the
API serves, the web app renders and the brief exporter turns into Markdown. Every number is computed here by
the functions in :mod:`market_almanac.analytics.shocks`, the same ones the offline catalog uses, so a
discovery row and the investigation it opens cannot disagree.

Nothing here infers a cause. The evidence section (:mod:`market_almanac.analytics.evidence`) states which
mechanisms the available data are consistent with, which they argue against, and which cannot be assessed
because the necessary data are not integrated.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from market_almanac.analytics.shocks import (
    BASELINE_MONTHS,
    EPISODE_CAVEAT,
    METHOD,
    METHOD_VERSION,
    MIN_ASSESSABLE_PEERS,
    Z_ELEVATED,
    against,
    baseline,
    compute_signals,
    episode_at,
    extent,
    find_episodes,
    seasonal_expectation,
    state_near,
    withheld_text,
)

CONFIG_FORMAT = "investigation-1"
MAX_PEERS = 60
MAX_MARKET_SERIES = 40
MAX_WINDOW_MONTHS = 240
DEFAULT_PRE_MONTHS = 24
DEFAULT_POST_MONTHS = 12
CPI_CODE = "IMF.CPI.ALL"
FX_CODE = "IMF.FX.USD"


class InvestigationError(ValueError):
    """The requested configuration cannot be investigated (the message says why)."""


def _iso(t: Any) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).date().isoformat()


def _ym(t: Any) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _month(v: str | None) -> pd.Timestamp | None:
    if not v:
        return None
    try:
        return pd.Timestamp(f"{v[:7]}-01")
    except (ValueError, TypeError) as exc:
        raise InvestigationError(f"not a month: {v!r} (use YYYY-MM)") from exc


def _months(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


# --- configuration --------------------------------------------------------------------------------------


def config_id(config: dict[str, Any]) -> str:
    """Stable identifier of a configuration (canonical JSON, SHA-256, first 16 hex characters)."""
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def resolve_config(
    series_id: str,
    sig: pd.DataFrame,
    episodes: list[dict[str, Any]],
    snapshot_id: str,
    event: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fill defaults deterministically: the event is the requested month, else the most recent unusual rise."""
    if sig.empty or not sig["observed"].any():
        raise InvestigationError("this series has no valid price observations")
    first, last = sig.index[sig["observed"]].min(), sig.index[sig["observed"]].max()
    ev = _month(event)
    chosen = None
    if ev is None:
        ups = [e for e in episodes if e["kind"] == "unusual" and e["direction"] == "up" and not e["data_concern"]]
        pool = ups or [e for e in episodes if e["kind"] == "unusual"] or episodes
        if pool:
            chosen = max(pool, key=lambda e: (e["peak"], abs(e.get("peak_yoy_pct") or 0)))
            ev = pd.Timestamp(chosen["peak"])
        else:
            ev = last
    if ev < first or ev > last:
        raise InvestigationError(f"the event month must lie within the series ({_ym(first)} to {_ym(last)})")
    chosen = chosen or episode_at(episodes, ev)
    s0 = _month(start)
    e0 = _month(end)
    if s0 is None:
        anchor = pd.Timestamp(chosen["start"]) if chosen else ev
        s0 = max(first, anchor - pd.DateOffset(months=DEFAULT_PRE_MONTHS))
    if e0 is None:
        anchor = pd.Timestamp(chosen["end"]) if chosen else ev
        e0 = min(last, anchor + pd.DateOffset(months=DEFAULT_POST_MONTHS))
    s0, e0 = max(s0, first), min(e0, last)
    if not s0 <= ev <= e0:
        raise InvestigationError("the window must contain the event month")
    if _months(s0, e0) + 1 > MAX_WINDOW_MONTHS:
        raise InvestigationError(f"the window may span at most {MAX_WINDOW_MONTHS} months")
    config = {
        "format": CONFIG_FORMAT,
        "method_version": METHOD_VERSION,
        "series_id": series_id,
        "event": _ym(ev),
        "window": {"start": _ym(s0), "end": _ym(e0)},
        "peers": "same country, commodity, unit, price type and currency",
        "snapshot_id": snapshot_id,
    }
    return config, chosen


# --- sections -------------------------------------------------------------------------------------------


def _observation_quality(
    raw: pd.DataFrame | None, sig: pd.DataFrame, s0: pd.Timestamp, e0: pd.Timestamp
) -> dict[str, Any]:
    win = sig.loc[s0:e0]
    missing = [_ym(t) for t in win.index[~win["observed"].to_numpy(dtype=bool)]]
    gap = best = 0
    for o in win["observed"]:
        gap = 0 if o else gap + 1
        best = max(best, gap)
    out: dict[str, Any] = {
        "months_in_window": len(win),
        "months_observed": int(win["observed"].sum()),
        "months_missing": len(missing),
        "missing_months": missing[:120],
        "longest_gap_months": best,
        "records_in_window": None,
        "records_not_used": None,
        "flagged_records": [],
    }
    if raw is not None and len(raw):
        r = raw.copy()
        r["period"] = pd.to_datetime(r["period"]).dt.normalize()
        r = r[(r["period"] >= s0) & (r["period"] <= e0)]
        out["records_in_window"] = len(r)
        if "used" in r:
            out["records_not_used"] = int((~r["used"].astype(bool)).sum())
        flagged = r[r["quality_flags"].fillna("").astype(str).str.len() > 0]
        out["flagged_records"] = [
            {
                "period": _ym(x["period"]),
                "price": _f(x["price"]),
                "flags": [f for f in str(x["quality_flags"]).split(";") if f],
                "used": bool(x["used"]) if "used" in x else None,
            }
            for _, x in flagged.head(50).iterrows()
        ]
    return out


def _signal_rows(sig: pd.DataFrame, s0: pd.Timestamp, e0: pd.Timestamp) -> list[dict[str, Any]]:
    rows = []
    for t, r in sig.loc[s0:e0].iterrows():
        rows.append(
            {
                "period": _ym(t),
                "price": _f(r["price"]),
                "mom_pct": _f(np.expm1(r["r1"])),
                "yoy_pct": _f(np.expm1(r["r12"])),
                "z": _f(r["z"]),
                "percentile": _f(r["percentile"]),
                "status": r["status"],
                "reason": r["reason"] or None,
            }
        )
    return rows


def _index_panel(
    own: pd.Series,
    panel: dict[str, pd.Series],
    base_start: pd.Timestamp,
    base_end: pd.Timestamp,
    s0: pd.Timestamp,
    e0: pd.Timestamp,
) -> dict[str, Any]:
    """Each series indexed to 100 = its own mean over the baseline months; peers summarised by median and IQR."""

    def idx(p: pd.Series) -> pd.Series | None:
        b = p[(p.index >= base_start) & (p.index <= base_end)].dropna()
        if len(b) < 3:
            return None
        return 100 * p / float(b.mean())

    months = pd.date_range(s0, e0, freq="MS")
    own_i = idx(own)
    cols = {sid: i.reindex(months) for sid, p in panel.items() if (i := idx(p)) is not None}
    frame = pd.DataFrame(cols, index=months)
    n = frame.notna().sum(axis=1)
    med = frame.median(axis=1)
    q25 = frame.quantile(0.25, axis=1)
    q75 = frame.quantile(0.75, axis=1)
    return {
        "base": {"start": _ym(base_start), "end": _ym(base_end)},
        "n_indexed_peers": len(cols),
        "rows": [
            {
                "period": _ym(t),
                "own": _f(own_i.get(t)) if own_i is not None else None,
                "peer_median": _f(med[t]) if n[t] >= 3 else None,
                "peer_q25": _f(q25[t]) if n[t] >= 3 else None,
                "peer_q75": _f(q75[t]) if n[t] >= 3 else None,
                "peers_observed": int(n[t]),
            }
            for t in months
        ],
    }


def _peer_rows(
    signals: dict[str, pd.DataFrame], meta: dict[str, dict[str, Any]], month: pd.Timestamp, direction: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    states, rows = [], []
    for sid in sorted(signals):
        st = state_near(signals[sid], month, direction)
        states.append(st)
        m = meta.get(sid, {})
        rows.append(
            {
                "series_id": sid,
                "market_name": m.get("market_name"),
                "admin1_name": m.get("admin1_name"),
                "commodity_name": m.get("commodity_name"),
                "unit": m.get("unit"),
                "price_type": m.get("price_type"),
                "status": st.get("status"),
                "reason": REASON_SHORT.get(str(st.get("reason") or st.get("status")))
                if st.get("status") != "ok"
                else None,
                "period": st.get("period"),
                "yoy_pct": _f(st.get("yoy_pct")),
                "z": _f(st.get("z")),
                "elevated": st.get("elevated"),
            }
        )
    sign = -1.0 if direction == "up" else 1.0

    def order(r: dict[str, Any]) -> tuple[bool, float]:
        z = r["z"]
        return (r["status"] != "ok", sign * float(z) if z is not None else float("inf"))

    rows.sort(key=order)
    return states, rows


REASON_SHORT = {
    "short_history": "too little earlier history",
    "few_years": "earlier history spans too few years",
    "sparse_recent": "too many recent months missing",
    "degenerate_history": "earlier prices barely varied",
    "no_change_observed": "no 12-month change within a month of the peak",
    "no_data": "no valid prices",
}
BREADTH_CLASS = {"widespread": "broad", "local": "narrow", "mixed": "mixed", "inconclusive": "inconclusive"}


def _macro(macro: pd.DataFrame | None, iso3: str, month: pd.Timestamp, yoy: float | None) -> dict[str, Any]:
    out: dict[str, Any] = {"cpi": None, "fx": None, "real_yoy_pct": None, "available": []}
    if macro is None or macro.empty:
        return out
    m = macro[macro["country_iso3"] == iso3].copy()
    if m.empty:
        return out
    m["period"] = pd.to_datetime(m["period"]).dt.normalize()

    def yoy_of(code: str) -> dict[str, Any] | None:
        s = m[(m["indicator_code"] == code)].set_index("period")["value"].astype(float).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        if month not in s.index or (month - pd.DateOffset(months=12)) not in s.index:
            return None
        prev = float(s[month - pd.DateOffset(months=12)])
        if prev <= 0:
            return None
        row = m[m["indicator_code"] == code].iloc[0]
        return {
            "indicator_code": code,
            "indicator_name": str(row["indicator_name"]),
            "unit": str(row["unit"]),
            "provider": str(row["provider"]),
            "period": _ym(month),
            "value": float(s[month]),
            "yoy_pct": float(s[month] / prev - 1),
            "series": [
                {"period": _ym(t), "value": float(v)}
                for t, v in s.loc[month - pd.DateOffset(months=36) : month].items()
            ],
        }

    out["cpi"] = yoy_of(CPI_CODE)
    out["fx"] = yoy_of(FX_CODE)
    out["available"] = [k for k in ("cpi", "fx") if out[k]]
    if out["cpi"] and yoy is not None:
        out["real_yoy_pct"] = float((1 + yoy) / (1 + out["cpi"]["yoy_pct"]) - 1)
    return out


def _weather(env: dict[str, Any] | None, month: pd.Timestamp) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "unavailable", "market_cell": None, "production_region": None}
    if not env or env.get("status") != "ok":
        return out
    lo = month - pd.DateOffset(months=12)
    cell = [r for r in env.get("market_cell_series", []) if lo <= pd.Timestamp(r["period"]) <= month]
    rz = [r["rain_anomaly_z"] for r in cell if r.get("rain_anomaly_z") is not None]
    if cell:
        out["market_cell"] = {
            "months": len(cell),
            "mean_rain_anomaly_z": _f(np.mean(rz)) if rz else None,
            "months_rain_below_minus_1_5": sum(1 for z in rz if z <= -1.5),
            "months_rain_above_1_5": sum(1 for z in rz if z >= 1.5),
            "basis": (env.get("market_cell") or {}).get("basis"),
            "window": {"start": _ym(lo), "end": _ym(month)},
        }
    prod = [r for r in env.get("production_region_series", []) if lo <= pd.Timestamp(r["period"]) <= month]
    pr = [r for r in prod if r.get("season_rain_anomaly_z") is not None]
    if pr:
        last = pr[-1]
        out["production_region"] = {
            "crop": (env.get("production_region") or {}).get("crop"),
            "period": _ym(last["period"]),
            "season_rain_anomaly_z": _f(last["season_rain_anomaly_z"]),
            "min_season_rain_anomaly_z": _f(min(r["season_rain_anomaly_z"] for r in pr)),
            "basis": (env.get("production_region") or {}).get("basis"),
        }
    out["status"] = "ok" if (out["market_cell"] or out["production_region"]) else "unavailable"
    out["evaluated_as_explanation"] = False
    out["note"] = (
        "Contextual evidence only. Weather was not evaluated as an explanation for this event, and Market Almanac's "
        "pre-registered studies did not establish that these measurements improve price forecasts."
    )
    return out


def _persistence(ep: dict[str, Any] | None) -> dict[str, Any]:
    if not ep:
        return {"verdict": "no_episode"}
    d = ep["duration_months"]
    verdict = "ongoing" if ep["ongoing"] else "single_month" if d == 1 else "short" if d <= 3 else "persistent"
    return {
        "verdict": verdict,
        "duration_months": d,
        "qualifying_months": ep["qualifying_months"],
        "ongoing": ep["ongoing"],
        "retrace_6m_pct": ep.get("retrace_6m_pct"),
        "note": EPISODE_CAVEAT,
    }


# --- main entry -----------------------------------------------------------------------------------------


def investigate(
    *,
    series_id: str,
    meta: dict[str, Any],
    prices: pd.Series,
    snapshot_id: str,
    raw: pd.DataFrame | None = None,
    peers: dict[str, tuple[dict[str, Any], pd.Series]] | None = None,
    market_series: dict[str, tuple[dict[str, Any], pd.Series]] | None = None,
    macro: pd.DataFrame | None = None,
    environment: dict[str, Any] | None = None,
    event: str | None = None,
    start: str | None = None,
    end: str | None = None,
    country_name: str | None = None,
    peers_available: int | None = None,
    market_available: int | None = None,
) -> dict[str, Any]:
    """Assemble the investigation document (see the module docstring).

    ``peers_available`` and ``market_available`` are how many comparable markets and other foods exist before the
    caps on how many are read; they let the evidence say how many of the markets found were actually assessed.
    """
    from market_almanac.analytics.evidence import build_evidence

    sig = compute_signals(prices)
    episodes = find_episodes(sig)
    config, chosen = resolve_config(series_id, sig, episodes, snapshot_id, event, start, end)
    ev = pd.Timestamp(f"{config['event']}-01")
    s0 = pd.Timestamp(f"{config['window']['start']}-01")
    e0 = pd.Timestamp(f"{config['window']['end']}-01")
    ep = episode_at(episodes, ev) if chosen is None else chosen
    direction = ep["direction"] if ep else ("up" if (sig.at[ev, "r12"] if ev in sig.index else 0) >= 0 else "down")
    onset = pd.Timestamp(ep["start"]) if ep else ev
    base = baseline(sig, onset)
    base_end = onset - pd.DateOffset(months=1)
    base_start = onset - pd.DateOffset(months=BASELINE_MONTHS)

    row = sig.loc[ev] if ev in sig.index else None
    r12 = _f(row["r12"]) if row is not None else None
    yoy = _f(np.expm1(r12)) if r12 is not None else None
    prior = sig.loc[sig.index < onset, "r12"].dropna().to_numpy()
    frozen = against(r12, prior) if r12 is not None and row is not None and row["status"] == "ok" else None
    if row is not None and row["status"] == "withheld":
        unusual = {"status": "withheld", "reason": row["reason"], "text": withheld_text(str(row["reason"]), row)}
    elif row is None or r12 is None:
        unusual = {
            "status": "withheld",
            "reason": "no_12m_change",
            "text": "no 12-month change can be computed for this month (it or the same month a year earlier is "
            "missing)",
        }
    else:
        z = _f(frozen["z"]) if frozen else None
        unusual = {
            "status": "ok",
            "z": z,
            "percentile": _f(frozen["percentile"]) if frozen else None,
            "n_reference": len(prior),
            "reference_years": len({t.year for t in sig.index[(sig.index < onset) & sig["r12"].notna()]}),
            "reference_median_yoy_pct": _f(np.expm1(frozen["reference_median"])) if frozen else None,
            "reference_p10_yoy_pct": _f(np.expm1(frozen["reference_p10"])) if frozen else None,
            "reference_p90_yoy_pct": _f(np.expm1(frozen["reference_p90"])) if frozen else None,
            "band_upper_yoy_pct": _f(np.expm1(frozen["reference_median"] + Z_ELEVATED * frozen["reference_scale"]))
            if frozen
            else None,
            "band_lower_yoy_pct": _f(np.expm1(frozen["reference_median"] - Z_ELEVATED * frozen["reference_scale"]))
            if frozen
            else None,
            "label": "unusual" if z is not None and abs(z) >= Z_ELEVATED else "typical",
            "stable": len(prior) >= 60,
            "reference_ends": _ym(onset - pd.DateOffset(months=1)),
        }

    peak = pd.Timestamp(ep["peak"]) if ep else ev
    peak_price = _f(sig.at[peak, "price"]) if peak in sig.index else None
    magnitude = {
        "event_price": _f(row["price"]) if row is not None else None,
        "event_yoy_pct": yoy,
        "event_mom_pct": _f(np.expm1(row["r1"])) if row is not None else None,
        "baseline": base,
        "change_from_baseline_pct": _f(row["price"] / base["mean_price"] - 1) if base and row is not None else None,
        "peak_month": _ym(peak),
        "peak_price": peak_price,
        "peak_index": _f(100 * peak_price / base["mean_price"]) if base and peak_price else None,
        "large_nominal": bool(yoy is not None and abs(yoy) >= 0.25),
    }

    peer_sig = {sid: compute_signals(p) for sid, (_, p) in list((peers or {}).items())[:MAX_PEERS]}
    peer_meta = {sid: m for sid, (m, _) in (peers or {}).items()}
    states, peer_rows = _peer_rows(peer_sig, peer_meta, peak, direction)
    peer_extent = extent(states)
    index_panel = _index_panel(
        sig["price"], {sid: s["price"] for sid, s in peer_sig.items()}, base_start, base_end, s0, e0
    )

    mk_sig = {sid: compute_signals(p) for sid, (_, p) in list((market_series or {}).items())[:MAX_MARKET_SERIES]}
    mk_meta = {sid: m for sid, (m, _) in (market_series or {}).items()}
    mk_states, mk_rows = _peer_rows(mk_sig, mk_meta, peak, direction)
    breadth = extent(mk_states)
    breadth["class"] = BREADTH_CLASS[breadth["class"]]
    breadth["rule"] = (
        "broad: >= 50% of the other assessable foods in the same market elevated in the same direction (robust z "
        "beyond 2 in 2 of the 3 months around the peak); narrow: < 25%; inconclusive: fewer than "
        f"{MIN_ASSESSABLE_PEERS} assessable"
    )

    seasonal = seasonal_expectation(sig, onset, peak) if ep else {"status": "no_episode"}
    in_window = [e for e in episodes if e["end"] >= _iso(s0) and e["start"] <= _iso(e0)]  # type: ignore[operator]

    doc: dict[str, Any] = {
        "config": config,
        "config_id": config_id(config),
        "method": {"version": METHOD_VERSION, "text": METHOD},
        "subject": {
            "series_id": series_id,
            "country_iso3": meta.get("country_iso3"),
            "country_name": country_name or meta.get("country_iso3"),
            "market_name": meta.get("market_name"),
            "admin1_name": meta.get("admin1_name"),
            "admin2_name": meta.get("admin2_name"),
            "commodity_name": meta.get("commodity_name"),
            "unit": meta.get("unit"),
            "price_type": meta.get("price_type"),
            "price_flag": meta.get("price_flag"),
            "currency": meta.get("currency"),
            "first_period": _ym(sig.index[sig["observed"]].min()),
            "last_period": _ym(sig.index[sig["observed"]].max()),
            "n_observations": int(sig["observed"].sum()),
        },
        "episode": ep,
        "episodes_in_window": in_window,
        "direction": direction,
        "magnitude": magnitude,
        "unusualness": unusual,
        "persistence": _persistence(ep),
        "seasonality": seasonal,
        "peers": {
            "extent": peer_extent,
            "rows": peer_rows,
            "index": index_panel,
            "capped_at": MAX_PEERS,
            "n_available": peers_available,
        },
        "breadth": {
            "extent": breadth,
            "rows": mk_rows,
            "capped_at": MAX_MARKET_SERIES,
            "n_available": market_available,
        },
        "context": {
            "weather": _weather(environment, ev),
            "macro": _macro(macro, str(meta.get("country_iso3")), ev, yoy),
        },
        "observation_quality": _observation_quality(raw, sig, s0, e0),
        "signals": _signal_rows(sig, s0, e0),
    }
    doc["question"] = research_question(doc)
    doc["evidence"] = build_evidence(doc)
    return doc


def research_question(doc: dict[str, Any]) -> str:
    s = doc["subject"]
    ev = pd.Timestamp(f"{doc['config']['event']}-01")
    verb = "rise" if doc["direction"] == "up" else "fall"
    return (
        f"Was the {verb} in the {str(s['price_type']).lower()} price of {s['commodity_name']} in {s['market_name']} "
        f"({s['country_name']}) around {ev.strftime('%B %Y')} unusual for that market, was it shared by comparable "
        "markets and other foods, and what can the available data say about why it happened?"
    )
