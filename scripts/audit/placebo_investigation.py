"""Audit v1.1, Audit 2: why does the 60-month time-shifted weather placebo score better than real weather?

Exploratory. Nothing here changes or replaces the frozen confirmatory results. Inputs are the
archived per-group ``features.parquet`` and ``predictions.parquet`` of
``data/studies/live/forecastability-atlas-v1``. Model refits use the independent ridge in
``independent_trace.py`` (no ``market_almanac`` import), which reproduces every archived ridge
prediction to < 1e-14.

    uv run python -I scripts/audit/placebo_investigation.py data/studies/live/forecastability-atlas-v1 \
        docs/audits/evidence/atlas_v1/placebo_investigation.json
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import independent_trace as T

TEST_START = pd.Timestamp("2022-01-01")
VARIANTS = ("primary", "weather_time_shift_60", "weather_permuted_cells")


def dm(d: np.ndarray, h: int) -> dict:
    """One-sided DM (H1: E d > 0) with the protocol's HAC lag rule and HLN correction."""
    n = len(d)
    q = max(h - 1, math.floor(4 * (n / 100) ** (2 / 9)))
    e = d - d.mean()
    v = e @ e / n + sum(2 * (1 - k / (q + 1)) * (e[k:] @ e[:-k]) / n for k in range(1, q + 1))
    s = d.mean() / math.sqrt(v / n) * math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return {"stat": float(s), "p_one_sided": float(stats.t.sf(s, n - 1)), "T": n, "lags": q}


def monthly(rows: pd.DataFrame, la: str, lb: str) -> pd.DataFrame:
    c = rows.groupby(["origin", "country_iso3"])[[la, lb]].mean()
    return c.groupby(level="origin").mean().sort_index()


def ratio(rows: pd.DataFrame, la: str, lb: str) -> float:
    m = monthly(rows, la, lb)
    return float(m[lb].sum() / m[la].sum())


def collect(root: Path, h: int) -> pd.DataFrame:
    """One row per (series, origin) with y, naive, ridge_A and ridge_B of every variant."""
    out = []
    for d in sorted(glob.glob(str(root / "experiments" / "*__primary"))):
        gid = d.split("__")[1]
        frames = {}
        for v in VARIANTS:
            p = pd.read_parquet(d.replace("__primary", f"__{v}") + "/predictions.parquet")
            p = p[(p["task"] == "regression") & (p["horizon"] == h) & (p["origin"] >= TEST_START)]
            frames[v] = p.pivot_table(index=["series_id", "origin"], columns="model", values="pred")
            if v == "primary":
                if p.empty:
                    break
                y = p.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])["y"]
        if len(frames) < len(VARIANTS):
            continue  # no forecasts at this horizon for this group
        w = pd.DataFrame({"y": y, "naive": frames["primary"]["naive"], "A": frames["primary"]["ridge_A"]})
        for v in VARIANTS:
            w[f"B_{v}"] = frames[v]["ridge_B"]
        w = w.dropna().reset_index()
        w["group_id"], w["country_iso3"] = gid, gid[:3]
        out.append(w)
    r = pd.concat(out, ignore_index=True)
    r["lA"] = (r["y"] - r["A"]) ** 2
    r["lN"] = r["y"] ** 2
    for v in VARIANTS:
        r[f"l_{v}"] = (r["y"] - r[f"B_{v}"]) ** 2
    return r


def counterfactual(root: Path, h: int, mode: str) -> pd.DataFrame:
    rows = []
    for d in sorted(glob.glob(str(root / "experiments" / "*__primary"))):
        gid = d.split("__")[1]
        for v in VARIANTS:
            f = pd.read_parquet(d.replace("__primary", f"__{v}") + "/features.parquet")
            f = f.rename(columns={"y_dlog_h1": "y_h1", "y_dlog_h3": "y_h3"})
            try:
                bt = T.backtest(f, h, alpha_mode=mode)
            except (ValueError, KeyError):
                continue  # e.g. no test origin at this horizon
            bt = bt[bt["origin"] >= TEST_START][
                ["series_id", "origin", "y", "ridge_A", "ridge_B", "alpha_A", "alpha_B", "refit"]
            ]
            bt["variant"], bt["group_id"], bt["country_iso3"] = v, gid, gid[:3]
            rows.append(bt)
    return pd.concat(rows, ignore_index=True)


def main(root_s: str, out_s: str) -> int:
    root = Path(root_s)
    rep: dict = {"note": "exploratory audit analysis; the frozen confirmatory results are unchanged"}
    for h in (1, 3):
        r = collect(root, h)
        hr: dict = {"n_matched_forecasts": len(r)}
        # 1. headline ratios on one common matched sample, with and without PSE
        for name, sub in (("all", r), ("excluding_PSE", r[r["country_iso3"] != "PSE"])):
            hr[name] = {v: ratio(sub, "lA", f"l_{v}") for v in VARIANTS}
            hr[name]["A_vs_naive"] = ratio(sub, "lN", "lA")
            for v in VARIANTS:
                m = monthly(sub, "lA", f"l_{v}")
                hr[name][f"dm_{v}_B_better_than_A"] = dm((m["lA"] - m[f"l_{v}"]).to_numpy(), h)
        # 2. real weather against each placebo directly (d > 0 means real weather has lower loss)
        for v in VARIANTS[1:]:
            m = monthly(r, f"l_{v}", "l_primary")
            hr[f"real_vs_{v}"] = {
                "ratio_real_over_placebo": float(m["l_primary"].sum() / m[f"l_{v}"].sum()),
                "dm_real_better": dm((m[f"l_{v}"] - m["l_primary"]).to_numpy(), h),
            }
        # 3. where does the A-minus-B difference come from? country-weighted contributions
        c = r.groupby(["origin", "country_iso3"])[["lA", *[f"l_{v}" for v in VARIANTS]]].mean()
        w = 1 / c.groupby(level="origin").size()
        c = c.mul(w.reindex(c.index.get_level_values(0)).to_numpy(), axis=0)
        tot_a = float(c["lA"].sum())
        contrib = pd.DataFrame({v: c["lA"] - c[f"l_{v}"] for v in VARIANTS})
        by_c = contrib.groupby(level="country_iso3").sum()
        hr["share_of_A_loss_PSE"] = float(c["lA"].groupby(level="country_iso3").sum().get("PSE", 0) / tot_a)
        hr["difference_total"] = {v: float(contrib[v].sum()) for v in VARIANTS}
        hr["difference_from_PSE"] = {v: float(by_c[v].get("PSE", 0)) for v in VARIANTS}
        hr["top5_country_months_shift60"] = [
            {"origin": str(k[0].date()), "country": k[1], "contribution": float(x)}
            for k, x in contrib["weather_time_shift_60"].sort_values(ascending=False).head(5).items()
        ]
        top_group = (
            r.assign(d=r["lA"] - r["l_weather_time_shift_60"]).groupby(["group_id"])["d"].sum().sort_values().tail(3)
        )
        hr["top_groups_raw_difference_shift60"] = {k: float(x) for k, x in top_group.items()}
        rep[f"h{h}"] = hr
        # 4. tuning: penalties chosen, and counterfactuals with the penalty held fixed
        cf = {}
        for mode in ("nested", "B_uses_A", "10.0", "100.0"):
            x = counterfactual(root, h, mode)
            x["lA"], x["lB"] = (x["y"] - x["ridge_A"]) ** 2, (x["y"] - x["ridge_B"]) ** 2
            res = {}
            for v in VARIANTS:
                s = x[x["variant"] == v]
                res[v] = {
                    "all": ratio(s, "lA", "lB"),
                    "excluding_PSE": ratio(s[s["country_iso3"] != "PSE"], "lA", "lB"),
                }
            if mode == "nested":
                k = ["group_id", "refit"]
                al = x.drop_duplicates([*k, "variant"]).pivot_table(index=k, columns="variant", values="alpha_B")
                res["share_folds_alpha_B_differs_shift60_vs_primary"] = float(
                    (al["weather_time_shift_60"] != al["primary"]).mean()
                )
                res["share_folds_alpha_B_differs_permuted_vs_primary"] = float(
                    (al["weather_permuted_cells"] != al["primary"]).mean()
                )
                res["n_group_folds"] = len(al)
            cf[mode] = res
        rep[f"h{h}"]["penalty_counterfactuals"] = cf
    Path(out_s).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
