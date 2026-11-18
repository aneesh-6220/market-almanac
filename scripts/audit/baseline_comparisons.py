"""Audit v1.1, Audit 4: matched baseline comparisons for Forecastability Atlas v1 (exploratory).

Separate from the frozen confirmatory family (H1, H2). Recomputes, from
``predictions_primary.parquet`` only and without importing ``market_almanac``:

    ridge_A vs naive, ridge_B vs naive, ridge_B vs ridge_A, and each against seasonal-naive,

at h = 1 and 3, on the matched (series, origin) sample of each pair, reporting forecast counts,
months, countries, the country-balanced loss ratio, a one-sided DM p (protocol HAC/HLN rule), a
two-way bootstrap interval, and sensitivity to influential countries and months: without PSE,
leave-one-country-out range, without the 3 most influential months, the median per-country
ratio, a 1%-winsorised-loss ratio and the series-pooled (unweighted) ratio.

    uv run python -I scripts/audit/baseline_comparisons.py data/studies/live/forecastability-atlas-v1 \
        docs/audits/evidence/atlas_v1/baseline_comparisons.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inference_monte_carlo import boot, dm

PAIRS = [
    ("naive", "ridge_A"),
    ("naive", "ridge_B"),
    ("ridge_A", "ridge_B"),
    ("seasonal_naive", "naive"),
    ("seasonal_naive", "ridge_A"),
    ("seasonal_naive", "ridge_B"),
]


def matched(p: pd.DataFrame, a: str, b: str, h: int) -> pd.DataFrame:
    q = p[(p["horizon"] == h) & (p["origin"] >= pd.Timestamp("2022-01-01"))]
    w = q.pivot_table(index=["country_iso3", "series_id", "origin"], columns="model", values="pred", aggfunc="first")
    y = q.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])["y"]
    w = w[[a, b]].dropna().reset_index()
    w["y"] = y.reindex(pd.MultiIndex.from_frame(w[["series_id", "origin"]])).to_numpy()
    w = w[np.isfinite(w["y"])]
    w["la"], w["lb"] = (w["y"] - w[a]) ** 2, (w["y"] - w[b]) ** 2
    return w


def panel(w: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    c = w.groupby(["country_iso3", "origin"])[["la", "lb"]].mean()
    A = c["la"].unstack("origin").sort_index(axis=1)
    B = c["lb"].unstack("origin").reindex_like(A)
    return A.to_numpy(), B.to_numpy(), c


def r_(A: np.ndarray, B: np.ndarray) -> float:
    return float(np.nansum(np.nanmean(B, 0)) / np.nansum(np.nanmean(A, 0)))


def compare(w: pd.DataFrame, h: int, rng: np.random.Generator) -> dict:
    A, B, c = panel(w)
    ma, mb = np.nanmean(A, 0), np.nanmean(B, 0)
    lo, hi = boot(A, B, h, 1000, rng, "two_way", 0)
    countries = sorted(w["country_iso3"].unique())
    loco = {}
    for k in countries:
        s = w[w["country_iso3"] != k]
        a2, b2, _ = panel(s)
        loco[k] = r_(a2, b2)
    diff = ma - mb
    top = np.argsort(-np.abs(diff))[:3]
    keep = np.setdiff1d(np.arange(len(diff)), top)
    pc = c.groupby(level="country_iso3").mean()
    cut = np.quantile(np.r_[w["la"], w["lb"]], 0.99)
    ww = w.assign(la=w["la"].clip(upper=cut), lb=w["lb"].clip(upper=cut))
    aw, bw, _ = panel(ww)
    nopse = w[w["country_iso3"] != "PSE"]
    a3, b3, _ = panel(nopse)
    m3 = (np.nanmean(a3, 0), np.nanmean(b3, 0))
    return {
        "n_forecasts": len(w),
        "n_series": int(w["series_id"].nunique()),
        "n_months": int(A.shape[1]),
        "n_countries": len(countries),
        "ratio": r_(A, B),
        "dm_p_challenger_better": dm(diff, h),
        "dm_p_challenger_worse": dm(-diff, h),
        "two_way_ci95": [lo, hi],
        "ratio_without_PSE": r_(a3, b3),
        "dm_p_better_without_PSE": dm(m3[0] - m3[1], h),
        "loco_min": [min(loco, key=loco.get), min(loco.values())],
        "loco_max": [max(loco, key=loco.get), max(loco.values())],
        "ratio_without_top3_months": float(mb[keep].sum() / ma[keep].sum()),
        "median_country_ratio": float(np.median(pc["lb"] / pc["la"])),
        "countries_better_worse": [int((pc["lb"] < pc["la"]).sum()), int((pc["lb"] > pc["la"]).sum())],
        "ratio_losses_winsorised_p99": r_(aw, bw),
        "ratio_series_pooled": float(w["lb"].sum() / w["la"].sum()),
    }


def main(root_s: str, out_s: str) -> int:
    p = pd.read_parquet(Path(root_s) / "predictions_primary.parquet")
    p = p[p["task"] == "regression"]
    rng = np.random.default_rng(20261118)
    out = []
    for h in (1, 3):
        for a, b in PAIRS:
            r = compare(matched(p, a, b, h), h, rng)
            out.append({"horizon": h, "baseline": a, "challenger": b, **r})
            print(
                f"h={h} {b:>14} vs {a:<14} n={r['n_forecasts']:6d} T={r['n_months']} C={r['n_countries']} "
                f"ratio={r['ratio']:.4f} CI=[{r['two_way_ci95'][0]:.3f},{r['two_way_ci95'][1]:.3f}] "
                f"p_better={r['dm_p_challenger_better']:.3f} exPSE={r['ratio_without_PSE']:.4f} "
                f"(p={r['dm_p_better_without_PSE']:.3f}) med_c={r['median_country_ratio']:.3f} "
                f"wins={r['ratio_losses_winsorised_p99']:.4f} pooled={r['ratio_series_pooled']:.4f} "
                f"loco=[{r['loco_min'][1]:.3f},{r['loco_max'][1]:.3f}] b/w={r['countries_better_worse']}"
            )
    Path(out_s).write_text(
        json.dumps({"note": "exploratory; not part of the confirmatory family", "rows": out}, indent=1)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
