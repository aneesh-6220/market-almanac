"""The economic-context engine: one local price series placed beside macroeconomic and international context.

Input: a country, a monthly local-currency price series (with the investigation's event, onset, peak and window), a
context snapshot, and an optional ``as_of`` month. Output: a JSON-safe section (format ``economic-context-1``) with

* **indicator series**: headline CPI, food CPI, exchange rates (period average and end of period) and the mapped
  international benchmarks, each with coverage, freshness, base breaks and an explicit state when it cannot be used;
* **aligned changes**: every series expressed as a 12-month change at the event month and as a change from the
  pre-episode baseline to the peak, so the same arithmetic is applied to all of them;
* **relative changes**: the local price relative to headline CPI and to food CPI (a relative-price statement), the
  USD value of the price, and a benchmark's local-currency change split exactly into dollar price and exchange rate;
* **descriptive lag comparisons**: Spearman correlations of monthly log changes at several leads, all of them, never
  the best one, with explicit insufficiency;
* **warnings** (currency regimes, official-rate caution, quote direction, mapping confidence, base breaks, vintage),
  **missing states**, and **lineage** (source references, vintages, per-series SHA-256, the transformations applied).

Nothing here states a cause. Wording is generated separately by :mod:`market_almanac.analytics.economic_evidence`
from this structure; the structure holds numbers and states only, plus the curated limitation texts of the reference
tables. Everything is computed from the in-memory snapshot: no network, no database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from market_almanac.context import CONTEXT_FORMAT, METHOD_VERSION
from market_almanac.context import transforms as T
from market_almanac.context.reference import benchmark_def, benchmark_mapping, benchmark_table, regime_for, regimes
from market_almanac.context.release import series_hashes
from market_almanac.context.store import ContextSnapshot

MAX_BENCHMARKS = 3
LAGS = (0, 1, 2, 3, 4, 5, 6)
FRESH_MONTHS = 6
TRANSFORMS = {
    "yoy": "12-month change = level(t) / level(t-12) - 1 over calendar months; withheld if either month is missing or "
    "a base break lies between them",
    "baseline": "change from the mean level over the 12 months before the episode onset to the level at the peak; "
    "withheld with fewer than 3 baseline months, a missing peak month or a base break in between",
    "index": "each series indexed to 100 = its own mean over the baseline months, so series in different units share "
    "one axis; withheld on the far side of a base break",
    "relative": "(1 + price change) / (1 + deflator change) - 1: how the price moved relative to the national basket; "
    "not purchasing power, not a causal share",
    "usd_price": "local price / domestic currency per USD (period average), month by month: an indicative dollar value "
    "at the official rate",
    "local_benchmark": "benchmark USD price x domestic currency per USD (period average); its log change splits "
    "exactly into the benchmark's log change and the exchange rate's",
    "lag": "Spearman correlation between monthly log changes of the local price at t and of the reference at t - lag; "
    "no p-values; fewer than 24 paired months is insufficient",
}


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _ym(t: Any) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m")


def _ts(ym: str) -> pd.Timestamp:
    return pd.Timestamp(f"{ym}-01")


@dataclass
class Loaded:
    """One series as available to this analysis (after any ``as_of`` release-lag filter) and why, if it is not."""

    key: str
    row: dict[str, Any] | None
    levels: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    breaks: list[pd.Timestamp] = field(default_factory=list)
    state: str = "ok"  # ok | no_series | empty_series | not_yet_available
    reason: str = ""
    n_removed_by_as_of: int = 0

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def load(snap: ContextSnapshot, key: str, as_of: pd.Timestamp | None) -> Loaded:
    row = snap.row(key)
    if row is None:
        return Loaded(key, None, state="no_series", reason="the source publishes no such series for this country")
    if not row["n_obs"]:
        why = (
            f"the series exists but all {int(row['n_source_empty'] or 0)} of its months are empty in the source"
            if row["n_source_empty"]
            else "the series has no valid observations"
        )
        if row["n_rejected"]:
            why += f" ({int(row['n_rejected'])} observation(s) failed validation)"
        return Loaded(key, row, state="empty_series", reason=why)
    levels = T.as_monthly(snap.series(key))
    breaks = [_ts(b) for b in str(row["base_breaks"] or "").split(",") if b]
    kept = T.available_as_of(levels, int(row["release_lag_months"] or 0), as_of)
    removed = int(len(levels) - len(kept))
    if kept.empty:
        return Loaded(
            key, row, breaks=breaks, state="not_yet_available", reason="nothing was published by the as-of month"
        )
    return Loaded(key, row, kept, breaks, n_removed_by_as_of=removed)


def _why(levels: pd.Series, breaks: list[pd.Timestamp], a: pd.Timestamp, b: pd.Timestamp) -> str | None:
    """Why the change from month ``a`` to month ``b`` is unavailable (None when it is available)."""
    if b not in levels.index:
        if levels.empty or b > levels.index.max():
            return f"the series ends in {_ym(levels.index.max())}, before {_ym(b)}"
        if b < levels.index.min():
            return f"the series starts in {_ym(levels.index.min())}, after {_ym(b)}"
        return f"{_ym(b)} is missing in the source"
    if a not in levels.index or pd.isna(levels[a]):
        if a < levels.index.min():
            return f"the series starts in {_ym(levels.index.min())}, after {_ym(a)}"
        return f"{_ym(a)} is missing in the source"
    if any(a < br <= b for br in breaks):
        hit = next(br for br in breaks if a < br <= b)
        return f"the series was re-based in {_ym(hit)} and was not spliced, so levels either side are not comparable"
    return None


def change(
    levels: pd.Series, breaks: list[pd.Timestamp], a: pd.Timestamp, b: pd.Timestamp
) -> tuple[float | None, str | None]:
    why = _why(levels, breaks, a, b)
    if why:
        return None, why
    v = T.change_between(levels, a, b, breaks)
    return (v, None) if v is not None else (None, "the earlier level is not positive")


def baseline_change(
    levels: pd.Series, breaks: list[pd.Timestamp], base_start: pd.Timestamp, base_end: pd.Timestamp, month: pd.Timestamp
) -> tuple[float | None, str | None]:
    """Change from the mean level over the baseline months to the level in ``month``."""
    if any(base_start < br <= base_end for br in breaks):
        return None, "the baseline months straddle a base break"
    if any(base_end < br <= month for br in breaks):
        hit = next(br for br in breaks if base_end < br <= month)
        return None, f"the series was re-based in {_ym(hit)}, between the baseline and {_ym(month)}"
    base = levels[(levels.index >= base_start) & (levels.index <= base_end)].dropna()
    if len(base) < 3:
        return None, f"fewer than 3 baseline months observed ({len(base)})"
    if month not in levels.index or pd.isna(levels[month]):
        return None, f"{_ym(month)} is not observed"
    m = float(base.mean())
    return (float(levels[month] / m - 1.0), None) if m > 0 else (None, "the baseline mean is not positive")


def indexed(
    levels: pd.Series,
    breaks: list[pd.Timestamp],
    base_start: pd.Timestamp,
    base_end: pd.Timestamp,
    months: pd.DatetimeIndex,
) -> pd.Series | None:
    """100 = mean over the baseline; months on the far side of a base break are blanked."""
    if any(base_start < br <= base_end for br in breaks):
        return None
    ix = T.rebase(levels, base_start, base_end)
    if ix is None:
        return None
    out = ix.reindex(months)
    for t in months:
        after = t > base_end and any(base_end < br <= t for br in breaks)
        before = t < base_start and any(t < br <= base_start for br in breaks)
        if after or before:
            out[t] = np.nan
    return out


def _coverage(
    ld: Loaded, event: pd.Timestamp, s0: pd.Timestamp, e0: pd.Timestamp, newest: pd.Timestamp | None
) -> dict[str, Any]:
    r = ld.row or {}
    lv = ld.levels
    window = pd.date_range(s0, e0, freq="MS")
    observed = int(lv.reindex(window).notna().sum()) if not lv.empty else 0
    last = lv.index.max() if not lv.empty else None
    stale = bool(
        newest is not None
        and last is not None
        and (newest.year - last.year) * 12 + newest.month - last.month > FRESH_MONTHS
    )
    return {
        "first_period": _ym(lv.index.min()) if not lv.empty else r.get("first_period"),
        "last_period": _ym(last) if last is not None else r.get("last_period"),
        "n_obs": len(lv),
        "n_source_empty": int(r.get("n_source_empty") or 0),
        "n_rejected": int(r.get("n_rejected") or 0),
        "months_in_window": len(window),
        "months_observed_in_window": observed,
        "months_missing_in_window": int(len(window) - observed),
        "ends_before_event": bool(last is not None and last < event),
        "stale": stale,
        "release_lag_months": int(r.get("release_lag_months") or 0),
        "removed_by_as_of": ld.n_removed_by_as_of,
    }


@dataclass
class Engine:
    snap: ContextSnapshot
    iso3: str
    price: pd.Series
    event: pd.Timestamp
    onset: pd.Timestamp
    peak: pd.Timestamp
    s0: pd.Timestamp
    e0: pd.Timestamp
    currency: str | None
    commodity_name: str
    as_of: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        self.base_end = self.onset - pd.DateOffset(months=1)
        self.base_start = self.onset - pd.DateOffset(months=12)
        self.months = pd.date_range(self.s0, self.e0, freq="MS")
        self.price = T.as_monthly(self.price)
        t = self.snap.series_table()
        self.newest = max((_ts(x) for x in t["last_period"].dropna() if str(x) < "9999"), default=None)
        self.used: dict[str, Loaded] = {}
        self.missing: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []

    # -- helpers ------------------------------------------------------------------------------------------------

    def _load(self, key: str, label: str) -> Loaded:
        ld = load(self.snap, key, self.as_of)
        self.used[key] = ld
        if not ld.ok:
            self.missing.append({"key": key, "label": label, "state": ld.state, "reason": ld.reason})
        return ld

    def _warn(self, code: str, text: str, severity: str = "info") -> None:
        if not any(w["code"] == code and w["text"] == text for w in self.warnings):
            self.warnings.append({"code": code, "severity": severity, "text": text})

    def _indicator(
        self, key: str, label: str, unit: str, *, local_per_usd: bool = False
    ) -> tuple[dict[str, Any], Loaded]:
        ld = self._load(key, label)
        out: dict[str, Any] = {
            "series_key": key,
            "label": label,
            "unit": unit,
            "state": ld.state,
            "reason": ld.reason or None,
            "base_period": (ld.row or {}).get("base_period"),
            "source_ref": (ld.row or {}).get("source_ref"),
        }
        if not ld.ok:
            out |= {"coverage": _coverage(ld, self.event, self.s0, self.e0, self.newest) if ld.row else None}
            return out, ld
        yoy, yoy_why = change(ld.levels, ld.breaks, self.event - pd.DateOffset(months=12), self.event)
        peak, peak_why = baseline_change(ld.levels, ld.breaks, self.base_start, self.base_end, self.peak)
        mom, mom_why = change(ld.levels, ld.breaks, self.event - pd.DateOffset(months=1), self.event)
        out |= {
            "coverage": _coverage(ld, self.event, self.s0, self.e0, self.newest),
            "level_at_event": _f(ld.levels.get(self.event)),
            "yoy_pct": yoy,
            "yoy_unavailable_reason": yoy_why,
            "mom_pct": mom,
            "mom_unavailable_reason": mom_why,
            "baseline_to_peak_pct": peak,
            "baseline_to_peak_unavailable_reason": peak_why,
            "base_breaks": [_ym(b) for b in ld.breaks],
            "base_breaks_in_window": [
                _ym(b) for b in ld.breaks if self.event - pd.DateOffset(months=12) < b <= self.e0
            ],
        }
        if out["base_breaks_in_window"]:
            self._warn(
                "base_break",
                f"{label} for {self.iso3} was re-based in {', '.join(out['base_breaks_in_window'])} and the two parts "
                "were not spliced by the source; changes spanning the break are withheld.",
                "warn",
            )
        if out["coverage"]["stale"]:
            self._warn(
                "stale_series",
                f"{label} for {self.iso3} ends in {out['coverage']['last_period']}, well before "
                "the newest data in the snapshot.",
                "warn",
            )
        iv = indexed(ld.levels, ld.breaks, self.base_start, self.base_end, self.months)
        out["chart_index"] = None if iv is None else [_f(v) for v in iv]
        if local_per_usd:
            steps = [
                s
                for s in T.fx_step_changes(ld.levels)
                if self.event - pd.DateOffset(months=12) < _ts(s["period"]) <= self.e0
            ]
            out["step_changes_in_window"] = steps
            if steps:
                self._warn(
                    "fx_step",
                    f"The official {label.lower()} moved by 25% or more in a single month ("
                    + ", ".join(f"{s['period']} {s['mom_pct'] * 100:+.0f}%" for s in steps[:4])
                    + "), typical of a devaluation, a regime change or a unification of rates.",
                    "warn",
                )
            out["usd_value_change_yoy_pct"] = T.usd_value_change(yoy) if yoy is not None else None
        return out, ld

    # -- sections -----------------------------------------------------------------------------------------------

    def inflation(self) -> tuple[dict[str, Any], dict[str, Loaded]]:
        head, lh = self._indicator(f"imf.cpi_headline.{self.iso3}", "Consumer price index (all items)", "index")
        food, lf = self._indicator(
            f"imf.cpi_food.{self.iso3}", "Consumer price index (food and non-alcoholic beverages)", "index"
        )
        out: dict[str, Any] = {"headline": head, "food": food}
        if lh.ok and lf.ok:
            fy, hy = food.get("yoy_pct"), head.get("yoy_pct")
            out["food_minus_headline_yoy_pp"] = None if fy is None or hy is None else (fy - hy) * 100
        return out, {"headline": lh, "food": lf}

    def exchange_rate(self) -> tuple[dict[str, Any], dict[str, Loaded], dict[str, Any]]:
        pa, lpa = self._indicator(
            f"imf.fx_period_avg.{self.iso3}",
            "Exchange rate, period average (domestic currency per US dollar)",
            "domestic currency per USD",
            local_per_usd=True,
        )
        eop, leop = self._indicator(
            f"imf.fx_end_period.{self.iso3}",
            "Exchange rate, end of period (domestic currency per US dollar)",
            "domestic currency per USD",
            local_per_usd=True,
        )
        regs = regime_for(self.iso3)
        peg = [e for e in regs if e["kind"] in ("currency_union_peg", "peg")]
        doll = [e for e in regs if e["kind"] == "dollarized"]
        caution = [e for e in regs if e["kind"] == "official_rate_caution"]
        pc = (self.currency or "").upper()
        applic, verified = "applies", False
        if not (lpa.ok or leop.ok):
            applic = "no_series"
        elif pc == "USD":
            applic = "price_in_usd"
            self._warn(
                "price_in_usd",
                "The price is recorded in US dollars, so the national exchange rate does not convert "
                "it; the rate is shown as context only.",
                "info",
            )
        elif doll:
            applic = "dollarized"
        elif peg:
            codes = set(str(peg[0]["currency"]).split("/"))
            if pc and pc not in codes:
                applic = "currency_mismatch"
            else:
                verified = bool(pc)
        if applic == "currency_mismatch":
            self._warn(
                "currency_mismatch",
                f"The price is in {pc} but the country's currency regime lists "
                f"{peg[0]['currency']}; the IMF exchange-rate series is for the national currency and is not applied.",
                "warn",
            )
        if applic == "dollarized":
            self._warn("dollarized", doll[0]["interpretation"], "warn")
        for e in peg:
            self._warn("peg", f"{e['currency_name']} ({e['currency']}): {e['interpretation']}", "info")
        for e in caution:
            self._warn(
                "official_rate_caution",
                f"{self.iso3} is listed among the countries for which this applies. {e['interpretation']}",
                "warn",
            )
        if not regs:
            self._warn(
                "regime_unclassified",
                f"{self.iso3}'s exchange-rate arrangement is not classified in the reference "
                "table (it is not assumed to float).",
                "info",
            )
        if applic == "applies" and not verified:
            self._warn(
                "currency_assumed",
                "The price's currency is assumed to be the national currency of the IMF "
                "exchange-rate series (not independently verifiable here).",
                "info",
            )
        out = {
            "quote": "domestic currency per US dollar: a rise means more units of the local currency per dollar "
            "(a weaker local currency against the dollar); the dollar value of one local unit moves as 1/(1+x) - 1",
            "price_currency": self.currency,
            "applicability": applic,
            "currency_verified": verified,
            "regime": [
                {
                    k: e.get(k)
                    for k in (
                        "id",
                        "kind",
                        "currency",
                        "currency_name",
                        "anchor",
                        "fixed_rate",
                        "fixed_rate_quote",
                        "since",
                        "union",
                        "interpretation",
                    )
                }
                for e in regs
            ],
            "regime_reference": {"version": regimes()["version"], "reviewed": regimes()["last_reviewed"]},
            "period_average": pa,
            "end_period": eop,
        }
        if pa.get("yoy_pct") is not None and eop.get("yoy_pct") is not None:
            out["average_vs_end_period_yoy_pp"] = (eop["yoy_pct"] - pa["yoy_pct"]) * 100
        return out, {"pa": lpa, "eop": leop}, {"applicability": applic}

    def usd_price(self, lpa: Loaded) -> dict[str, Any]:
        usd = T.to_usd(self.price, lpa.levels)
        yoy, why = change(usd.dropna(), [], self.event - pd.DateOffset(months=12), self.event)
        peak, pwhy = baseline_change(usd.dropna(), [], self.base_start, self.base_end, self.peak)
        ix = indexed(usd.dropna(), [], self.base_start, self.base_end, self.months)
        return {
            "yoy_pct": yoy,
            "yoy_unavailable_reason": why,
            "baseline_to_peak_pct": peak,
            "baseline_to_peak_unavailable_reason": pwhy,
            "chart_index": None if ix is None else [_f(v) for v in ix],
            "note": "indicative: local price divided by the official period-average rate; households may have faced a "
            "different rate",
        }

    def benchmarks(self, lpa: Loaded, fx_applies: bool) -> dict[str, Any]:
        mp = benchmark_mapping(self.commodity_name)
        out: dict[str, Any] = {
            "commodity": self.commodity_name,
            "confidence": mp["confidence"],
            "role": mp.get("role"),
            "limitations": mp.get("limitations", []),
            "confidence_text": benchmark_table()["confidence_scale"].get(mp["confidence"]),
            "reference": {"version": benchmark_table()["version"], "reviewed": benchmark_table()["last_reviewed"]},
            "unit_note": "Benchmark levels are never compared with the local price: units, grades and places differ. "
            "Only changes and indexed paths are compared.",
            "items": [],
            "status": "ok",
        }
        ids = mp["benchmarks"][:MAX_BENCHMARKS]
        if not ids:
            out["status"] = "no_benchmark"
            out["reason"] = (
                benchmark_table().get("no_benchmark_note")
                if mp["confidence"] == "none"
                else "no benchmark is mapped to this commodity"
            )
            self.missing.append(
                {
                    "key": "benchmark",
                    "label": "International benchmark",
                    "state": "no_benchmark",
                    "reason": out["reason"],
                }
            )
            return out
        if mp["confidence"] in ("low", "none"):
            self._warn(
                "mapping_low_confidence",
                f"The benchmark mapping for {self.commodity_name} is rated "
                f"'{mp['confidence']}': {out['confidence_text']}",
                "warn",
            )
        defs = self.snap.definitions()
        for bid in ids:
            d = benchmark_def(bid)
            item, ld = self._indicator(f"wb.pink.{bid}", d["label"], d["unit"])
            item |= {
                "benchmark_id": bid,
                "definition": defs.get(bid),
                "summary": d.get("summary"),
            }
            if ld.ok:
                last = ld.levels.index.max()
                if last < self.e0:
                    self._warn(
                        "benchmark_ends",
                        f"{d['label']} ends in {_ym(last)}"
                        + (" (the World Bank discontinued the series)" if bid == "sorghum" else "")
                        + ".",
                        "warn",
                    )
                if fx_applies and lpa.ok:
                    loc = (ld.levels * lpa.levels.reindex(ld.levels.index)).dropna()
                    ly, lwhy = change(loc, [], self.event - pd.DateOffset(months=12), self.event)
                    lpk, lpwhy = baseline_change(loc, [], self.base_start, self.base_end, self.peak)
                    ix = indexed(loc, [], self.base_start, self.base_end, self.months)
                    dec = None
                    fxy = self._fx_yoy(lpa)
                    if item.get("yoy_pct") is not None and fxy is not None and ly is not None:
                        dec = T.decompose_log_change(item["yoy_pct"], fxy)
                    item["local_currency"] = {
                        "yoy_pct": ly,
                        "yoy_unavailable_reason": lwhy,
                        "baseline_to_peak_pct": lpk,
                        "baseline_to_peak_unavailable_reason": lpwhy,
                        "chart_index": None if ix is None else [_f(v) for v in ix],
                        "decomposition_yoy": dec,
                    }
                else:
                    item["local_currency"] = None
            out["items"].append(item)
        if not any(i["state"] == "ok" for i in out["items"]):
            out["status"] = "unavailable"
        return out

    def _fx_yoy(self, lpa: Loaded) -> float | None:
        return change(lpa.levels, lpa.breaks, self.event - pd.DateOffset(months=12), self.event)[0]

    def lags(self, refs: dict[str, tuple[str, pd.Series, list[pd.Timestamp]]]) -> dict[str, Any]:
        """Descriptive lagged comparisons with each reference, restricted to months up to the window end."""
        price = self.price[self.price.index <= self.e0]
        pairs = []
        for key, (label, levels, breaks) in refs.items():
            ref = levels[levels.index <= self.e0]
            rows = T.lagged_comparison(T.log_monthly_changes(price), T.log_monthly_changes(ref, breaks), LAGS)
            pairs.append(
                {
                    "key": key,
                    "label": label,
                    "n_pairs_lag0": rows[0].n,
                    "rows": [{"lag": r.lag, "n": r.n, "spearman": _f(r.spearman), "status": r.status} for r in rows],
                    "any_sufficient": any(r.status == "ok" for r in rows),
                }
            )
        return {
            "method": TRANSFORMS["lag"],
            "lags_months": list(LAGS),
            "through": _ym(self.e0),
            "pairs": pairs,
            "caution": "Descriptive. Seven lags are examined, monthly changes are autocorrelated and nothing about "
            "timing identifies a mechanism: the strongest lag is not a finding.",
        }

    # -- lineage ------------------------------------------------------------------------------------------------

    def lineage(self) -> list[dict[str, Any]]:
        out = []
        for key, ld in self.used.items():
            if not ld.row:
                continue
            r = ld.row
            src = self.snap.source(str(r["provider"]), str(r["dataset"]) if r["provider"] == "imf" else None)
            if r["provider"] == "imf":
                src = next(
                    (
                        s
                        for s in self.snap.manifest.get("sources", [])
                        if s["provider"] == "imf" and s["concept"] == r["concept"]
                    ),
                    src,
                )
            h = None
            if not ld.levels.empty:
                df = pd.DataFrame({"series_key": key, "period": ld.levels.index, "value": ld.levels.to_numpy()})
                h = series_hashes(df).get(key)
            out.append(
                {
                    "series_key": key,
                    "provider": r["provider"],
                    "dataset": r["dataset"],
                    "concept": r["concept"],
                    "label": r["label"],
                    "unit": r["unit"],
                    "source_ref": r["source_ref"],
                    "base_period": r["base_period"],
                    "first_period": r["first_period"],
                    "last_period": r["last_period"],
                    "release_lag_months_assumed": int(r["release_lag_months"] or 0),
                    "vintage_publication_date": (src or {}).get("publication_date"),
                    "retrieved_at": (src or {}).get("retrieved_at"),
                    "response_sha256": (src or {}).get("response_sha256") or (src or {}).get("workbook_sha256"),
                    "observations_sha256": h,
                    "licence": ((src or {}).get("licence") or {}).get("redistribution"),
                    "attribution": ((src or {}).get("licence") or {}).get("attribution"),
                }
            )
        return out


def _relative(
    label: str,
    key: str,
    nominal: float | None,
    deflator: float | None,
    horizon: str,
    why_n: str | None,
    why_d: str | None,
    dname: str,
) -> dict[str, Any]:
    if nominal is None or deflator is None:
        return {
            "key": key,
            "label": label,
            "horizon": horizon,
            "deflator": dname,
            "status": "withheld",
            "nominal_pct": nominal,
            "deflator_pct": deflator,
            "relative_pct": None,
            "reason": why_n if nominal is None else why_d,
        }
    return {
        "key": key,
        "label": label,
        "horizon": horizon,
        "deflator": dname,
        "status": "ok",
        "nominal_pct": nominal,
        "deflator_pct": deflator,
        "relative_pct": T.real_change(nominal, deflator),
        "reason": None,
    }


def economic_context(
    snap: ContextSnapshot,
    *,
    iso3: str,
    commodity_name: str,
    currency: str | None,
    price: pd.Series,
    event: pd.Timestamp,
    onset: pd.Timestamp,
    peak: pd.Timestamp,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    as_of: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Assemble the ``context.economic`` section (see the module docstring). Never raises for missing data: every
    absence is a state in the result."""
    eng = Engine(snap, iso3, price, event, onset, peak, window_start, window_end, currency, commodity_name, as_of)
    infl, lo = eng.inflation()
    fx, lfx, _ = eng.exchange_rate()
    applies = fx["applicability"] == "applies"
    lpa = lfx["pa"] if lfx["pa"].ok else lfx["eop"]
    if applies and not lfx["pa"].ok and lfx["eop"].ok:
        eng._warn(
            "fx_end_period_only",
            "Only the end-of-period exchange rate is available; it is used in place of the period average.",
            "info",
        )
    out: dict[str, Any] = {
        "format": CONTEXT_FORMAT,
        "method_version": METHOD_VERSION,
        "snapshot": {
            "snapshot_id": snap.snapshot_id,
            "observation_hash": snap.manifest.get("observation_hash"),
            "created_at": snap.manifest.get("created_at"),
            "vintage": "current archived vintage at retrieval: historical values may since have been revised, so "
            "comparisons of past months are exploratory, not a reconstruction of what was known then",
        },
        "as_of": _ym(as_of),
        "assumptions": {
            "release_lags_months": {c.concept: c.release_lag_months for c in _concepts()},
            "note": "release lags are assumptions, not verified publication dates",
        },
        "window": {
            "start": _ym(window_start),
            "end": _ym(window_end),
            "event": _ym(event),
            "onset": _ym(onset),
            "peak": _ym(peak),
            "baseline_start": _ym(eng.base_start),
            "baseline_end": _ym(eng.base_end),
        },
        "inflation": infl,
        "exchange_rate": fx,
    }
    price_yoy, pw = change(eng.price, [], event - pd.DateOffset(months=12), event)
    price_peak, ppw = baseline_change(eng.price, [], eng.base_start, eng.base_end, peak)
    out["price"] = {
        "currency": currency,
        "yoy_pct": price_yoy,
        "yoy_unavailable_reason": pw,
        "baseline_to_peak_pct": price_peak,
        "baseline_to_peak_unavailable_reason": ppw,
        "chart_index": _price_index(eng),
    }
    rel: list[dict[str, Any]] = []
    for horizon, pn, pwhy in (
        ("12-month change at the event month", price_yoy, pw),
        ("change from the pre-episode baseline to the peak", price_peak, ppw),
    ):
        k = "yoy_pct" if horizon.startswith("12") else "baseline_to_peak_pct"
        w = "yoy_unavailable_reason" if horizon.startswith("12") else "baseline_to_peak_unavailable_reason"
        for key, name, src in (
            ("price_vs_headline_cpi", "headline CPI", infl["headline"]),
            ("price_vs_food_cpi", "food CPI", infl["food"]),
        ):
            rel.append(
                _relative(
                    f"Price relative to {name}",
                    key,
                    pn,
                    src.get(k),
                    horizon,
                    pwhy,
                    src.get(w) or src.get("reason"),
                    name,
                )
            )
    out["relative_changes"] = rel
    if applies and lpa.ok:
        out["usd_price"] = eng.usd_price(lpa)
    else:
        out["usd_price"] = None
        eng.missing.append(
            {
                "key": "usd_price",
                "label": "Price in US dollars",
                "state": "not_applicable" if fx["applicability"] != "no_series" else "no_series",
                "reason": {
                    "price_in_usd": "the price is already in US dollars",
                    "dollarized": "the economy uses the US dollar",
                    "currency_mismatch": "the price currency differs from the national currency of the "
                    "exchange-rate series",
                    "no_series": "no exchange-rate series for this country",
                }.get(fx["applicability"], ""),
            }
        )
    out["international"] = eng.benchmarks(lpa, applies)

    refs: dict[str, tuple[str, pd.Series, list[pd.Timestamp]]] = {}
    for it in out["international"].get("items", []):
        if it["state"] == "ok":
            ld = eng.used[it["series_key"]]
            refs[f"benchmark:{it['benchmark_id']}"] = (f"{it['label']} (USD)", ld.levels, ld.breaks)
    if lpa.ok:
        refs["exchange_rate"] = ("Exchange rate (domestic currency per USD)", lpa.levels, lpa.breaks)
    if lo["headline"].ok:
        refs["cpi_headline"] = ("Consumer price index (all items)", lo["headline"].levels, lo["headline"].breaks)
    if lo["food"].ok:
        refs["cpi_food"] = ("Consumer price index (food)", lo["food"].levels, lo["food"].breaks)
    out["lags"] = eng.lags(refs)
    if as_of is None:
        eng._warn(
            "vintage_exploratory",
            "Historical comparisons use the current archived vintage of each series; revisions "
            "and re-basing since publication mean this is an exploratory reading, not what was visible at the time. "
            "Set an as-of month to apply the assumed release lags.",
            "info",
        )
    out["charts"] = {
        "months": [_ym(t) for t in eng.months],
        "baseline": {"start": _ym(eng.base_start), "end": _ym(eng.base_end)},
        "event": _ym(event),
        "unit": "index, 100 = each series' own mean over the baseline months",
    }
    out["missing"] = eng.missing
    out["warnings"] = eng.warnings
    out["lineage"] = eng.lineage()
    out["transformations"] = TRANSFORMS
    out["status"] = _status(out)
    out["context_id"] = context_id(out)
    return out


def _price_index(eng: Engine) -> list[float | None] | None:
    ix = indexed(eng.price, [], eng.base_start, eng.base_end, eng.months)
    return None if ix is None else [_f(v) for v in ix]


def _concepts() -> Any:
    from market_almanac.context.imf_ingest import CONCEPTS

    return CONCEPTS


def _status(out: dict[str, Any]) -> str:
    infl, fx, intl = out["inflation"], out["exchange_rate"], out["international"]
    any_ok = (
        infl["headline"]["state"] == "ok"
        or infl["food"]["state"] == "ok"
        or fx["period_average"]["state"] == "ok"
        or fx["end_period"]["state"] == "ok"
        or any(i["state"] == "ok" for i in intl.get("items", []))
    )
    return "ok" if any_ok else "no_context"


def context_id(out: dict[str, Any]) -> str:
    """Stable identifier of the context configuration: which snapshot, window, as-of, tables and method."""
    cfg = {
        "format": out["format"],
        "method": out["method_version"],
        "snapshot": out["snapshot"]["snapshot_id"],
        "as_of": out["as_of"],
        "window": out["window"],
        "benchmarks": benchmark_table()["version"],
        "regimes": regimes()["version"],
    }
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def unavailable(reason: str, state: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """The section when no context can be computed at all (nothing installed, metadata-only artefact, ...)."""
    return {
        "format": CONTEXT_FORMAT,
        "method_version": METHOD_VERSION,
        "status": state,
        "reason": reason,
        "snapshot": snapshot,
        "missing": [],
        "warnings": [],
        "lineage": [],
    }
