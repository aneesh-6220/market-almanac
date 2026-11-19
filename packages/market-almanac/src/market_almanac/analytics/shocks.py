"""Price-shock signals and episodes: which historical movements were unusual for the market where they happened.

This module extends :mod:`market_almanac.analytics.movement` (which assesses one month-on-month change) to whole
episodes, with the same conventions: log changes, robust statistics (median and MAD with a scale floor) and
reference sets that contain only earlier data.

Signal. For one comparable series with monthly prices P (observation month, nominal local currency), the
12-month change ending in month t is

    y_t = ln P_t - ln P_{t-12}            (only when both months were observed; never across a gap)

A 12-month change compares a month with the same calendar month a year earlier, so a regular seasonal
pattern cancels out and does not by itself make a month look unusual. y_t is compared with the 12-month
changes of the *same series* that ended before t:

    R_t = { y_s : s < t }
    z_t = (y_t - median R_t) / max(1.4826 MAD(R_t), SCALE_FLOOR)      robust z-score
    q_t = share of R_t strictly below y_t                             historical rank

The comparison is with the series' own history, so a large *nominal* change is not unusual where prices
habitually change that much (high-inflation economies), and a modest change can be unusual in a series that
rarely moves. Both numbers are always reported.

Eligibility. An assessment is withheld, with the reason, when

* fewer than MIN_REFERENCE earlier 12-month changes exist, or they come from fewer than MIN_REFERENCE_YEARS
  calendar years (12-month changes overlap, so 36 of them hold about three independent years of information);
* fewer than half of the 24 months up to t were observed (the change would rest on a sparse record);
* the earlier changes are degenerate (MAD below the scale floor: prices were mostly constant or carried
  forward), so "how variable is this market normally" cannot be estimated.

A z-score is never computed on a shorter or sparser record, however large the movement.

Episodes. A run of consecutive assessable months with z >= Z_ELEVATED (2; <= -2 for falls) is an *unusual
episode* if z reaches Z_TRIGGER (3, the Hampel identifier's threshold) in at least one of its months. The
two thresholds (hysteresis) keep ordinary noise out: under a normal distribution about 2.3% of months exceed 2
by chance but only 0.13% exceed 3, while a real shock keeps z above 2 for its whole duration, which is
therefore measured from where it crosses 2. One missing month inside a run does not break it. Its peak is the
month with the largest 12-month change, and the peak is re-assessed against the changes recorded *before the
episode began*, so an episode cannot dilute its own reference. Large nominal movements (|12-month change| >=
LARGE_NOMINAL) are listed separately so that the distinction stays visible: as *large but typical* when every
month stays within Z_ELEVATED of the earlier changes and the peak within it of the changes before the movement
began, and as *withheld* when they cannot be assessed. Large changes between the two thresholds that never reach
the trigger are neither and are not listed.

Everything here is descriptive. An episode says that prices in one market moved unusually compared with that
market's own past. It is not a finding of a shortage, a crisis or food insecurity, and it identifies no cause.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from market_almanac.analytics.movement import SCALE_FLOOR

METHOD_VERSION = "shock-1"
Z_ELEVATED = 2.0  # a month is "elevated"; an episode spans the run of elevated months ...
Z_TRIGGER = 3.0  # ... and counts as unusual only if it reaches this (Hampel's 3 x scaled MAD) at least once
MIN_REFERENCE = 36
MIN_REFERENCE_YEARS = 4
STABLE_REFERENCE = 60
COVERAGE_WINDOW = 24
MIN_RECENT_COVERAGE = 0.5
SPARSE_RECENT_COVERAGE = 0.75
MAX_BRIDGE_MONTHS = 1  # missing months that may sit inside one episode
LARGE_NOMINAL = 0.25  # |12-month change| treated as "large" in nominal terms (+25% / -25%)
BASELINE_MONTHS = 12
MIN_BASELINE_OBS = 6
REVERSAL_SHARE = 0.8
IMPLAUSIBLE_MONTHLY_FACTOR = 4.0  # a price x4 or /4 within one month: more often a unit or recording change

WITHHELD_TEXT = {
    "short_history": "fewer than {n} earlier 12-month changes to compare with (it has {have})",
    "few_years": "earlier 12-month changes come from only {have} calendar years (at least {n} are needed)",
    "sparse_recent": "fewer than half of the 24 months up to this month were observed ({have:.0%})",
    "degenerate_history": "earlier prices barely changed (half or more of the earlier 12-month changes are "
    "identical), so the series' normal variability cannot be estimated",
}

METHOD = (
    "12-month log price change compared with the same series' earlier 12-month changes (robust z-score: median "
    f"and 1.4826 x MAD, scale floor {SCALE_FLOOR}; rank: share of earlier changes below it). Assessed only with at "
    f"least {MIN_REFERENCE} earlier changes from {MIN_REFERENCE_YEARS}+ calendar years and at least "
    f"{MIN_RECENT_COVERAGE:.0%} of the last {COVERAGE_WINDOW} months observed. Episode: consecutive months with "
    f"|z| >= {Z_ELEVATED} that reaches |z| >= {Z_TRIGGER} at least once; its peak is re-assessed against "
    "changes recorded before it began."
)

SIGNAL_COLUMNS = [
    "price",
    "observed",
    "r1",
    "r12",
    "coverage24",
    "n_reference",
    "reference_years",
    "reference_median",
    "reference_scale",
    "scale_floored",
    "z",
    "percentile",
    "status",
    "reason",
]


def clean_monthly(price: pd.Series) -> pd.Series:
    """Strictly positive, finite prices, one per month (the first if a month repeats), sorted."""
    p = pd.to_numeric(price, errors="coerce")
    p = p[np.isfinite(p) & (p > 0)]
    if p.empty:
        return pd.Series(dtype="float64")
    p.index = pd.DatetimeIndex(p.index).to_period("M").to_timestamp()
    return p[~p.index.duplicated(keep="first")].sort_index().astype("float64")


def _months(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def against(x: float, ref: np.ndarray) -> dict[str, Any]:
    """Robust z and rank of ``x`` among ``ref`` (assumed already eligible)."""
    n = len(ref)
    if n == 0 or not np.isfinite(x):
        return {"n_reference": n, "z": None, "percentile": None, "reference_median": None, "reference_scale": None}
    med = float(np.median(ref))
    raw = 1.4826 * float(np.median(np.abs(ref - med)))
    scale = max(raw, SCALE_FLOOR)
    return {
        "n_reference": n,
        "z": (x - med) / scale,
        "percentile": float(np.mean(ref < x)),
        "reference_median": med,
        "reference_scale": scale,
        "scale_floored": raw < SCALE_FLOOR,
        "reference_p10": float(np.quantile(ref, 0.10)),
        "reference_p90": float(np.quantile(ref, 0.90)),
    }


def compute_signals(price: pd.Series) -> pd.DataFrame:
    """Per-month signals on a complete monthly index from the first to the last valid observation.

    Months without an observation stay in the index with ``observed = False`` and no changes, so a missing
    month is never read as a zero change.
    """
    p = clean_monthly(price)
    if p.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS, index=pd.DatetimeIndex([], name="period"))
    idx = pd.date_range(p.index.min(), p.index.max(), freq="MS", name="period")
    full = p.reindex(idx).to_numpy(dtype=float)
    lp = np.log(full)
    n = len(idx)
    obs = np.isfinite(lp)
    r1 = np.full(n, np.nan)
    r12 = np.full(n, np.nan)
    if n > 1:
        r1[1:] = lp[1:] - lp[:-1]
    if n > 12:
        r12[12:] = lp[12:] - lp[:-12]
    csum = np.concatenate([[0], np.cumsum(obs)])
    lo = np.maximum(np.arange(n) - (COVERAGE_WINDOW - 1), 0)
    cov = (csum[np.arange(n) + 1] - csum[lo]) / COVERAGE_WINDOW
    years = idx.year.to_numpy()

    n_ref = np.zeros(n, dtype=int)
    n_years = np.zeros(n, dtype=int)
    med = np.full(n, np.nan)
    scale = np.full(n, np.nan)
    floored = np.zeros(n, dtype=bool)
    z = np.full(n, np.nan)
    pct = np.full(n, np.nan)
    status = np.full(n, "none", dtype=object)
    reason = np.full(n, "", dtype=object)
    ref: list[float] = []
    ref_years: Counter[int] = Counter()
    for t in range(n):
        x = r12[t]
        if not np.isfinite(x):
            continue
        n_ref[t], n_years[t] = len(ref), len(ref_years)
        if len(ref) < MIN_REFERENCE:
            status[t], reason[t] = "withheld", "short_history"
        elif len(ref_years) < MIN_REFERENCE_YEARS:
            status[t], reason[t] = "withheld", "few_years"
        elif cov[t] < MIN_RECENT_COVERAGE:
            status[t], reason[t] = "withheld", "sparse_recent"
        else:
            arr = np.asarray(ref)
            k = len(arr)
            m = float(arr[k // 2]) if k % 2 else float((arr[k // 2 - 1] + arr[k // 2]) / 2)
            raw = 1.4826 * float(np.median(np.abs(arr - m)))
            med[t], floored[t] = m, raw < SCALE_FLOOR
            if raw < SCALE_FLOOR:
                status[t], reason[t] = "withheld", "degenerate_history"
            else:
                scale[t] = raw
                z[t] = (x - m) / raw
                pct[t] = bisect_left(ref, x) / k
                status[t] = "ok"
        insort(ref, float(x))
        ref_years[int(years[t])] += 1
    return pd.DataFrame(
        {
            "price": full,
            "observed": obs,
            "r1": r1,
            "r12": r12,
            "coverage24": cov,
            "n_reference": n_ref,
            "reference_years": n_years,
            "reference_median": med,
            "reference_scale": scale,
            "scale_floored": floored,
            "z": z,
            "percentile": pct,
            "status": status,
            "reason": reason,
        },
        index=idx,
    )


def withheld_text(reason: str, row: pd.Series | dict[str, Any]) -> str:
    if reason == "short_history":
        return WITHHELD_TEXT[reason].format(n=MIN_REFERENCE, have=int(row["n_reference"]))
    if reason == "few_years":
        return WITHHELD_TEXT[reason].format(n=MIN_REFERENCE_YEARS, have=int(row["reference_years"]))
    if reason == "sparse_recent":
        return WITHHELD_TEXT[reason].format(have=float(row["coverage24"]))
    return WITHHELD_TEXT.get(reason, reason)


def _iso(t: Any) -> str | None:
    return None if t is None or pd.isna(t) else pd.Timestamp(t).date().isoformat()


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _runs(months: list[pd.Timestamp], assessed: set[pd.Timestamp] | None = None) -> list[list[pd.Timestamp]]:
    """Group sorted months into runs. Up to MAX_BRIDGE_MONTHS months in between may be skipped, but only months
    without an assessment (missing or withheld): an assessed month that fails the rule always ends a run."""
    out: list[list[pd.Timestamp]] = []
    for t in months:
        if out:
            gap = _months(out[-1][-1], t)
            between = [out[-1][-1] + pd.DateOffset(months=k) for k in range(1, gap)]
            if gap <= MAX_BRIDGE_MONTHS + 1 and not (assessed and any(b in assessed for b in between)):
                out[-1].append(t)
                continue
        out.append([t])
    return out


def baseline(sig: pd.DataFrame, start: pd.Timestamp) -> dict[str, Any] | None:
    """Mean observed price over the BASELINE_MONTHS before ``start`` (None if fewer than MIN_BASELINE_OBS)."""
    lo = start - pd.DateOffset(months=BASELINE_MONTHS)
    w = sig.loc[(sig.index >= lo) & (sig.index < start), "price"].dropna()
    if len(w) < MIN_BASELINE_OBS:
        return None
    return {"start": _iso(lo), "end": _iso(start - pd.DateOffset(months=1)), "n": len(w), "mean_price": float(w.mean())}


def describe_episode(sig: pd.DataFrame, months: list[pd.Timestamp], direction: str, kind: str) -> dict[str, Any]:
    """Every quantity reported for one episode (``months``: the months that met the episode rule)."""
    start, end = months[0], months[-1]
    inside = sig.loc[start:end]
    r12 = inside["r12"]
    peak = r12.idxmax() if direction == "up" else r12.idxmin()
    prior = sig.loc[sig.index < start, "r12"].dropna().to_numpy()
    frozen = against(float(sig.at[peak, "r12"]), prior) if kind != "withheld" else {"n_reference": len(prior)}
    base = baseline(sig, start)
    peak_price = float(sig.at[peak, "price"])
    last_obs = sig.index[sig["observed"]].max()
    after = peak + pd.DateOffset(months=6)
    retrace = None
    if after in sig.index and np.isfinite(sig.at[after, "price"]):
        retrace = float(sig.at[after, "price"] / peak_price - 1)
    r1_in = inside["r1"].dropna()
    flags: list[str] = []
    if inside["observed"].sum() < len(inside):
        flags.append("missing_months_inside")
    nxt = sig.loc[sig.index > peak, "r1"].dropna()
    r1_peak = sig.at[peak, "r1"]
    if (
        len(months) == 1
        and np.isfinite(r1_peak)
        and len(nxt)
        and _months(peak, nxt.index[0]) == 1
        and np.sign(nxt.iloc[0]) == -np.sign(r1_peak)
        and abs(nxt.iloc[0]) >= REVERSAL_SHARE * abs(r1_peak)
    ):
        flags.append("single_month_reversed")
    comparison_month = peak - pd.DateOffset(months=12)
    if comparison_month in sig.index:
        cz = sig.at[comparison_month, "z"]
        if np.isfinite(cz) and abs(cz) >= Z_ELEVATED and np.sign(cz) != np.sign(sig.at[peak, "r12"]):
            flags.append("possible_base_effect")
    if kind != "withheld" and frozen.get("n_reference", 0) < STABLE_REFERENCE:
        flags.append("short_reference")
    jumps = sig.loc[start - pd.DateOffset(months=1) : end, "r1"].abs()
    if (jumps > np.log(IMPLAUSIBLE_MONTHLY_FACTOR)).any():
        flags.append("implausible_jump")
    if float(sig.at[peak, "coverage24"]) < SPARSE_RECENT_COVERAGE:
        flags.append("sparse_recent_record")
    win = sig.loc[start - pd.DateOffset(months=BASELINE_MONTHS) : end]
    out: dict[str, Any] = {
        "kind": kind,
        "direction": direction,
        "start": _iso(start),
        "peak": _iso(peak),
        "end": _iso(end),
        "duration_months": _months(start, end) + 1,
        "qualifying_months": len(months),
        "ongoing": bool(end == last_obs),
        "peak_price": peak_price,
        "peak_yoy_pct": float(np.exp(sig.at[peak, "r12"]) - 1),
        "onset_mom_pct": _f(np.exp(sig.at[start, "r1"]) - 1) if np.isfinite(sig.at[start, "r1"]) else None,
        "max_mom_pct": _f(np.exp(r1_in.max() if direction == "up" else r1_in.min()) - 1) if len(r1_in) else None,
        "peak_z": _f(frozen.get("z")),
        "peak_percentile": _f(frozen.get("percentile")),
        "n_reference": int(frozen.get("n_reference", 0)),
        "reference_years": len({t.year for t in sig.index[(sig.index < start) & sig["r12"].notna()]}),
        "reference_median_yoy_pct": _f(np.exp(frozen["reference_median"]) - 1)
        if frozen.get("reference_median") is not None
        else None,
        "stable": bool(frozen.get("n_reference", 0) >= STABLE_REFERENCE) if kind != "withheld" else False,
        "baseline": base,
        "peak_index": _f(100 * peak_price / base["mean_price"]) if base else None,
        "retrace_6m_pct": retrace,
        "window_coverage": float(win["observed"].mean()) if len(win) else None,
        "flags": flags,
        "data_concern": bool({"implausible_jump", "single_month_reversed"} & set(flags)),
        "withheld_reason": None,
    }
    if kind == "withheld":
        row = sig.loc[peak]
        out["withheld_reason"] = str(row["reason"])
        out["withheld_text"] = withheld_text(str(row["reason"]), row)
    return out


def find_episodes(sig: pd.DataFrame) -> list[dict[str, Any]]:
    """Unusual episodes, plus large nominal movements that were typical or could not be assessed."""
    if sig.empty:
        return []
    ok = sig["status"] == "ok"
    r12 = sig["r12"]
    big = np.log(1 + LARGE_NOMINAL)
    out = []
    for direction, sign in (("up", 1.0), ("down", -1.0)):
        z = sign * sig["z"]
        elevated = (ok & (z >= Z_ELEVATED)).fillna(False).to_numpy(dtype=bool)
        unusual_months: list[pd.Timestamp] = []
        assessed = set(sig.index[ok.to_numpy(dtype=bool)])
        for run in _runs(list(sig.index[elevated]), assessed):
            if float(z.loc[run].max()) >= Z_TRIGGER:
                out.append(describe_episode(sig, run, direction, "unusual"))
                unusual_months += run
        in_unusual = sig.index.isin(unusual_months)
        large = (sign * r12 >= (big if sign > 0 else -np.log(1 - LARGE_NOMINAL))).fillna(False).to_numpy(dtype=bool)
        # "typical" must hold on both references: every month within +/-Z_ELEVATED of the changes before it, and
        # the peak within it of the changes before the movement began. Large changes between the two thresholds
        # that never reach the trigger are neither unusual episodes nor typical; they are not catalogued (they
        # can still be investigated directly).
        within = (ok & (z < Z_ELEVATED)).fillna(False).to_numpy(dtype=bool)
        typical = ok.to_numpy(dtype=bool) & ~in_unusual & large & within
        withheld = (sig["status"] == "withheld").to_numpy(dtype=bool) & large
        for kind, mask in (("large_typical", typical), ("withheld", withheld)):
            for run in _runs(list(sig.index[mask]), set(sig.index[sig["r12"].notna().to_numpy(dtype=bool)])):
                ep = describe_episode(sig, run, direction, kind)
                if kind == "large_typical" and ep["peak_z"] is not None and abs(ep["peak_z"]) >= Z_ELEVATED:
                    continue
                out.append(ep)
    out.sort(key=lambda e: (e["start"], e["direction"], e["kind"]))
    return out


def episode_at(episodes: list[dict[str, Any]], month: pd.Timestamp, kinds: tuple[str, ...] | None = None) -> Any:
    """The episode whose span contains ``month`` (unusual first, then large typical, then withheld)."""
    m = _iso(month)
    order = {"unusual": 0, "large_typical": 1, "withheld": 2}
    hits = [e for e in episodes if e["start"] <= m <= e["end"] and (kinds is None or e["kind"] in kinds)]
    return min(hits, key=lambda e: (order[e["kind"]], -abs(e["peak_yoy_pct"]))) if hits else None


# --- comparisons with other markets -------------------------------------------------------------------


PEER_MIN_ELEVATED_MONTHS = 2


def state_near(sig: pd.DataFrame, month: pd.Timestamp, direction: str, tolerance: int = 1) -> dict[str, Any]:
    """A series' assessment within ``tolerance`` months of ``month``.

    The series counts as *elevated* when its robust z is beyond Z_ELEVATED (same direction) in at least
    PEER_MIN_ELEVATED_MONTHS of those months (or in its only assessable month there): a sustained movement, which
    ordinary month-to-month noise rarely produces. The change and z reported are those of the most extreme
    assessable month in the window (or of the nearest month with a change when none is assessable).
    """
    if sig.empty:
        return {"status": "no_data"}
    lo, hi = month - pd.DateOffset(months=tolerance), month + pd.DateOffset(months=tolerance)
    w = sig.loc[lo:hi]
    w = w[w["r12"].notna()]
    if w.empty:
        return {"status": "no_change_observed"}
    okw = w[w["status"] == "ok"]
    sign = 1.0 if direction == "up" else -1.0
    if okw.empty:
        at = w.iloc[int(np.abs((w.index - month).days).argmin())]
        return {
            "status": "withheld",
            "reason": str(at["reason"]),
            "yoy_pct": float(np.exp(at["r12"]) - 1),
            "period": _iso(at.name),
        }
    best = okw.iloc[int(np.argmax(sign * okw["z"].to_numpy()))]
    hits = int((sign * okw["z"] >= Z_ELEVATED).sum())
    need = min(PEER_MIN_ELEVATED_MONTHS, len(okw))
    return {
        "status": "ok",
        "period": _iso(best.name),
        "yoy_pct": float(np.exp(best["r12"]) - 1),
        "z": float(best["z"]),
        "percentile": float(best["percentile"]),
        "elevated_months": hits,
        "assessed_months": len(okw),
        "elevated": bool(hits >= need),
        "same_direction": bool(np.sign(best["r12"]) == sign),
    }


EXTENT_TEXT = {
    "widespread": "most comparable markets in the country were also unusually {dir} at the same time",
    "mixed": "some comparable markets were also unusually {dir}, others were not",
    "local": "few comparable markets were elevated at the same time",
    "inconclusive": "too few comparable markets could be assessed to say whether the movement was local",
}
MIN_ASSESSABLE_PEERS = 3


def extent(states: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify whether a movement was shared, from peers' :func:`state_near` results."""
    assessable = [s for s in states if s.get("status") == "ok"]
    n = len(assessable)
    elevated = sum(bool(s["elevated"]) for s in assessable)
    same = sum(bool(s["same_direction"]) for s in assessable)
    share = elevated / n if n else None
    if n < MIN_ASSESSABLE_PEERS or share is None:
        cls = "inconclusive"
    elif share >= 0.5:
        cls = "widespread"
    elif share < 0.25:
        cls = "local"
    else:
        cls = "mixed"
    yoy = [s["yoy_pct"] for s in states if s.get("yoy_pct") is not None]
    return {
        "class": cls,
        "n_peers": len(states),
        "n_assessable": n,
        "n_elevated": elevated,
        "share_elevated": share,
        "share_same_direction": same / n if n else None,
        "n_with_change": len(yoy),
        "median_peer_yoy_pct": float(np.median(yoy)) if yoy else None,
        "rule": f"a peer is elevated when its robust z is beyond {Z_ELEVATED:g} in the same direction in at least "
        f"{PEER_MIN_ELEVATED_MONTHS} of the 3 months around the peak; widespread: >= 50% of assessable peers "
        f"elevated; local: < 25%; inconclusive: fewer than {MIN_ASSESSABLE_PEERS} assessable peers",
    }


# --- seasonality ----------------------------------------------------------------------------------------


def seasonal_expectation(sig: pd.DataFrame, start: pd.Timestamp, peak: pd.Timestamp) -> dict[str, Any]:
    """How much of the rise from the month before ``start`` to ``peak`` the usual seasonal pattern implies.

    The profile (median ratio of each month's price to its calendar-year mean) uses only years that ended
    before the episode began, so the episode does not shape its own seasonal benchmark.
    """
    from market_almanac.analytics.summary import seasonal_profile

    base_month = start - pd.DateOffset(months=1)
    pre = sig.loc[sig.index < start, "price"].dropna()
    pre = pre[pre.index.year < start.year]
    prof = seasonal_profile(pre)
    out: dict[str, Any] = {"status": prof["status"], "years_used": prof.get("years_used", 0)}
    if prof["status"] != "ok":
        out["note"] = prof.get("note", "no seasonal profile")
        return out
    med = {m["month"]: m["median_index"] for m in prof["months"]}
    if base_month.month not in med or peak.month not in med:
        return {**out, "status": "insufficient_history", "note": "calendar months missing from the profile"}
    expected = med[peak.month] / med[base_month.month] - 1
    observed = None
    if base_month in sig.index and np.isfinite(sig.at[base_month, "price"]):
        observed = float(sig.at[peak, "price"] / sig.at[base_month, "price"] - 1)
    share = None
    if observed is not None and observed > 0 and expected > 0:
        share = min(float(np.log1p(expected) / np.log1p(observed)), 1.0)
    if observed is None:
        verdict = "no_base_observation"
    elif share is not None and share >= 0.75:
        verdict = "largely_seasonal"
    elif share is not None and share >= 0.25:
        verdict = "partly_seasonal"
    else:
        verdict = "not_seasonal"
    return {
        **out,
        "base_month": _iso(base_month),
        "peak_month": _iso(peak),
        "expected_change_pct": float(expected),
        "observed_change_pct": observed,
        "share_explained": share,
        "verdict": verdict,
        "peak_calendar_month": int(prof["peak_month"]),
        "trough_calendar_month": int(prof["trough_month"]),
        "seasonal_amplitude": float(prof["seasonal_amplitude"]),
        "months": prof["months"],
        "method": "median across pre-episode years of price / calendar-year mean, by calendar month; expected "
        "change = profile(peak month) / profile(month before onset) - 1",
    }
