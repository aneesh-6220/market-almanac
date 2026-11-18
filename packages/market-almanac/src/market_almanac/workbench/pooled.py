"""Pooled multi-country forecast comparisons (pure functions; no I/O).

Estimand (``country_balanced``, the default): with squared-error losses L for a challenger (b)
and a baseline (a), first average over the series of a country within an origin month, then
over countries within the month::

    d_t   = mean_c [ mean_{i in c} (L_a,it - L_b,it) ]
    ratio = sum_t mean_c mean_i L_b,it / sum_t mean_c mean_i L_a,it

so every country present in a month counts once, however many markets it reports. Inference
treats the *origin month* as the unit: the Diebold-Mariano statistic uses a Newey-West
variance with at least h-1 lags (overlapping h-step forecasts) and the Harvey-Leybourne-Newbold
small-sample correction (``evaluation.inference.diebold_mariano``). Because all countries in a
month can share global shocks, a second interval resamples *countries* (cluster bootstrap) and
a sign test asks whether more countries improved than worsened. None of these treats thousands
of market-month forecasts as independent observations.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from market_almanac.evaluation.inference import diebold_mariano, holm_adjust, moving_block_bootstrap_ratio


def matched_losses(preds: pd.DataFrame, a: str, b: str, h: int, test_start: pd.Timestamp | None) -> pd.DataFrame:
    """Rows where both models forecast the same (series, origin) target; squared-error losses."""
    p = preds[(preds["task"] == "regression") & (preds["horizon"] == h) & preds["model"].isin([a, b])]
    if test_start is not None:
        p = p[p["origin"] >= test_start]
    wide = p.pivot_table(index=["country_iso3", "series_id", "origin"], columns="model", values="pred", aggfunc="first")
    if wide.empty or a not in wide or b not in wide:
        return pd.DataFrame(columns=["country_iso3", "series_id", "origin", "loss_a", "loss_b"])
    y = p.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])["y"]
    wide = wide.dropna(subset=[a, b]).reset_index()
    wide["y"] = y.reindex(pd.MultiIndex.from_frame(wide[["series_id", "origin"]])).to_numpy()
    wide = wide[np.isfinite(wide["y"]) & np.isfinite(wide[a]) & np.isfinite(wide[b])]
    wide["loss_a"] = (wide["y"] - wide[a]) ** 2
    wide["loss_b"] = (wide["y"] - wide[b]) ** 2
    return wide[["country_iso3", "series_id", "origin", "loss_a", "loss_b"]].reset_index(drop=True)


def aggregate(rows: pd.DataFrame, how: str = "country_balanced") -> pd.DataFrame:
    """One row per (origin, unit): unit is the country (balanced) or the series (pooled)."""
    if how == "series_pooled":
        return rows.rename(columns={"series_id": "unit"})[["origin", "country_iso3", "unit", "loss_a", "loss_b"]]
    if how != "country_balanced":
        raise ValueError("how must be 'country_balanced' or 'series_pooled'")
    g = rows.groupby(["origin", "country_iso3"])[["loss_a", "loss_b"]].mean().reset_index()
    g["unit"] = g["country_iso3"]
    return g


def _ratio(agg: pd.DataFrame) -> float:
    m = agg.groupby("origin")[["loss_a", "loss_b"]].mean()
    den = float(m["loss_a"].sum())
    return float(m["loss_b"].sum() / den) if den > 0 else float("nan")


def country_cluster_bootstrap(agg: pd.DataFrame, reps: int, seed: int, alpha: float) -> dict[str, Any]:
    countries = np.array(sorted(agg["country_iso3"].unique()))
    if len(countries) < 5:
        return {"ci_low": None, "ci_high": None, "reps": 0, "note": "fewer than 5 countries"}
    by_c = {c: g for c, g in agg.groupby("country_iso3")}
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for r in range(reps):
        draw = rng.choice(countries, size=len(countries), replace=True)
        # duplicate draws are distinct pseudo-countries so they keep their own weight within a month
        sample = pd.concat([by_c[c].assign(country_iso3=f"{c}#{k}") for k, c in enumerate(draw)], ignore_index=True)
        out[r] = _ratio(sample)
    out = out[np.isfinite(out)]
    return {
        "ci_low": float(np.quantile(out, alpha / 2)),
        "ci_high": float(np.quantile(out, 1 - alpha / 2)),
        "reps": len(out),
        "note": "countries resampled with replacement (dependence across markets within a country preserved)",
    }


def two_way_bootstrap(agg: pd.DataFrame, h: int, reps: int, seed: int, alpha: float) -> dict[str, Any]:
    """Resample countries (with replacement) and moving blocks of months jointly.

    Countries carry persistent heterogeneity; months carry shocks shared by every country. The
    country-only cluster bootstrap cannot see the second source and under-covers when it matters
    (``tests/scientific/test_workbench.py``); a month-block bootstrap of country-averaged losses
    treats the set of countries as fixed. Drawing both (a pigeonhole-style two-way bootstrap)
    reflects both sources and is, if anything, conservative.
    """
    countries = sorted(agg["country_iso3"].unique())
    months = sorted(agg["origin"].unique())
    T, C = len(months), len(countries)
    if C < 5 or T < 12:
        return {"ci_low": None, "ci_high": None, "reps": 0, "note": "needs at least 5 countries and 12 months"}
    A = agg.pivot_table(index="country_iso3", columns="origin", values="loss_a").reindex(
        index=countries, columns=months
    )
    B = agg.pivot_table(index="country_iso3", columns="origin", values="loss_b").reindex(
        index=countries, columns=months
    )
    a, b = A.to_numpy(), B.to_numpy()
    L = max(h, round(T ** (1 / 3)))
    nblocks = math.ceil(T / L)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    with np.errstate(invalid="ignore", divide="ignore"):
        for r in range(reps):
            ci = rng.integers(0, C, C)
            starts = rng.integers(0, T - L + 1, nblocks)
            ti = (starts[:, None] + np.arange(L)).ravel()[:T]
            sa, sb = a[np.ix_(ci, ti)], b[np.ix_(ci, ti)]
            ma, mb = np.nanmean(sa, axis=0), np.nanmean(sb, axis=0)
            ok = np.isfinite(ma) & np.isfinite(mb)
            out[r] = mb[ok].sum() / ma[ok].sum() if ok.any() and ma[ok].sum() > 0 else np.nan
    out = out[np.isfinite(out)]
    return {
        "ci_low": float(np.quantile(out, alpha / 2)),
        "ci_high": float(np.quantile(out, 1 - alpha / 2)),
        "reps": len(out),
        "block_length": L,
        "note": "countries and moving blocks of origin months resampled jointly",
    }


def per_country(rows: pd.DataFrame) -> pd.DataFrame:
    g = rows.groupby("country_iso3").agg(
        loss_a=("loss_a", "mean"),
        loss_b=("loss_b", "mean"),
        n_forecasts=("loss_a", "size"),
        n_series=("series_id", "nunique"),
        n_months=("origin", "nunique"),
    )
    g["ratio"] = g["loss_b"] / g["loss_a"]
    g["log_ratio"] = np.log(g["ratio"])
    return g.reset_index()


def sign_test(pc: pd.DataFrame) -> dict[str, Any]:
    better = int((pc["ratio"] < 1).sum())
    worse = int((pc["ratio"] > 1).sum())
    n = better + worse
    if n == 0:
        return {"better": 0, "worse": 0, "p_one_sided_better": None, "p_two_sided": None}
    return {
        "better": better,
        "worse": worse,
        "p_one_sided_better": float(stats.binomtest(better, n, 0.5, alternative="greater").pvalue),
        "p_two_sided": float(stats.binomtest(better, n, 0.5).pvalue),
        "median_ratio": float(np.exp(np.median(pc["log_ratio"]))),
    }


def influence(agg: pd.DataFrame, k: int = 3) -> dict[str, Any]:
    m = agg.groupby("origin")[["loss_a", "loss_b"]].mean()
    d = m["loss_a"] - m["loss_b"]
    total = float(d.sum())
    top = d.abs().sort_values(ascending=False).index[:k]
    rest = m.drop(index=top)
    share = float(d.loc[top].sum() / total) if total else float("nan")
    return {
        "top_months": [pd.Timestamp(t).date().isoformat() for t in top],
        "top_share_of_total_difference": share,
        "ratio_without_top": float(rest["loss_b"].sum() / rest["loss_a"].sum()) if len(rest) else None,
        "fragile": bool(np.isfinite(share) and abs(share) > 0.5),
    }


def leave_one_country_out(agg: pd.DataFrame) -> dict[str, Any]:
    vals = {c: _ratio(agg[agg["country_iso3"] != c]) for c in sorted(agg["country_iso3"].unique())}
    if not vals:
        return {"min": None, "max": None}
    lo, hi = min(vals, key=vals.__getitem__), max(vals, key=vals.__getitem__)
    return {"min": vals[lo], "min_without": lo, "max": vals[hi], "max_without": hi}


def compare(
    rows: pd.DataFrame,
    h: int,
    *,
    how: str = "country_balanced",
    bootstrap: str = "two_way_country_month",
    reps: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
    min_periods: int = 24,
) -> dict[str, Any]:
    """Pooled comparison of baseline a (loss_a) and challenger b (loss_b); ratio < 1 favours b."""
    if rows.empty:
        return {"status": "insufficient_data", "reason": "no matched forecasts"}
    agg = aggregate(rows, how)
    dm = diebold_mariano(agg["loss_a"], agg["loss_b"], agg["origin"], h, min_periods=min_periods)
    block = moving_block_bootstrap_ratio(
        agg["loss_a"], agg["loss_b"], agg["origin"], h, reps=reps, seed=seed, alpha=alpha
    )
    if bootstrap == "two_way_country_month":
        cluster = two_way_bootstrap(agg, h, reps, seed, alpha)
    elif bootstrap == "country_cluster":
        cluster = country_cluster_bootstrap(agg, reps, seed, alpha)
    else:
        cluster = None
    pc = per_country(rows)
    ratio = _ratio(agg)
    p_worse = None
    if dm.stat is not None:
        p_worse = float(stats.t.sf(-dm.stat, df=dm.n_periods - 1))  # one-sided: challenger has higher loss
    return {
        "status": "ok" if dm.stat is not None else "insufficient_data",
        "reason": dm.note or None,
        "aggregation": how,
        "n_months": dm.n_periods,
        "n_countries": int(rows["country_iso3"].nunique()),
        "n_series": int(rows["series_id"].nunique()),
        "n_forecasts": len(rows),
        "first_origin": pd.Timestamp(rows["origin"].min()).date().isoformat(),
        "last_origin": pd.Timestamp(rows["origin"].max()).date().isoformat(),
        "loss_ratio": ratio,
        "pct_change_in_loss": (ratio - 1) * 100 if math.isfinite(ratio) else None,
        "mean_loss_baseline": float(agg.groupby("origin")["loss_a"].mean().mean()),
        "mean_loss_challenger": float(agg.groupby("origin")["loss_b"].mean().mean()),
        "dm_stat": dm.stat,
        "hac_lags": dm.lags,
        "p_challenger_better": dm.p_value_b_better,
        "p_challenger_worse": p_worse,
        "p_two_sided": dm.p_value_two_sided,
        "ci_block": {k: block.get(k) for k in ("ci_low", "ci_high", "block_length", "reps")},
        "ci_primary": {**cluster, "method": bootstrap} if cluster else None,
        "sign_test_countries": sign_test(pc),
        "influence": influence(agg),
        "leave_one_country_out": leave_one_country_out(agg) if rows["country_iso3"].nunique() > 1 else None,
        "per_country": pc.to_dict(orient="records"),
    }


def adjust(p_values: list[float | None], method: str) -> list[float | None]:
    if method == "none":
        return list(p_values)
    if method == "holm":
        return holm_adjust(p_values)
    if method == "benjamini_hochberg":
        idx = [i for i, p in enumerate(p_values) if p is not None and np.isfinite(p)]
        out: list[float | None] = [None] * len(p_values)
        m = len(idx)
        order = sorted(idx, key=lambda i: p_values[i])  # type: ignore[arg-type, return-value]
        running = 1.0
        for rank in range(m, 0, -1):
            i = order[rank - 1]
            running = min(running, float(p_values[i]) * m / rank)  # type: ignore[arg-type]
            out[i] = running
        return out
    raise ValueError(f"unknown multiplicity method {method}")


def evidence(result: dict[str, Any], p_adj: float | None, alpha: float, alternative: str) -> dict[str, str]:
    """Plain classification of what one comparison established (never stronger than the test)."""
    if result.get("status") != "ok" or p_adj is None:
        return {"class": "insufficient_data", "text": "Too few evaluation months or countries to test."}
    ci = result.get("ci_primary") or {}
    hi = ci.get("ci_high") if ci.get("ci_high") is not None else (result.get("ci_block") or {}).get("ci_high")
    lo = ci.get("ci_low") if ci.get("ci_low") is not None else (result.get("ci_block") or {}).get("ci_low")
    if p_adj < alpha and (hi is None or hi < 1):
        fragile = (result.get("influence") or {}).get("fragile")
        return {
            "class": "improvement_fragile" if fragile else "improvement",
            "text": "Challenger had lower loss after multiplicity adjustment"
            + (" but the gain rests on a few months." if fragile else "."),
        }
    pw = result.get("p_challenger_worse")
    if pw is not None and pw < alpha and (lo is None or lo > 1):
        return {"class": "deterioration", "text": "Challenger had significantly higher loss than the baseline."}
    return {
        "class": "not_established",
        "text": "No improvement was established; this is not evidence that the information has no value.",
    }
