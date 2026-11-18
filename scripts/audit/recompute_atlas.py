"""Independent recomputation of the Forecastability Atlas confirmatory tests.

Reads only the stored per-forecast predictions (``predictions_primary.parquet``) and the study's
``results.json``, and recomputes H1 and H2 with pandas, numpy and scipy. It deliberately does not
import ``market_almanac``: the matching, aggregation, Newey-West variance, Harvey-Leybourne-Newbold
correction and Holm adjustment are written out again here, so an error in the project's inference
code would show up as a discrepancy.

Usage::

    uv run python scripts/audit/recompute_atlas.py data/studies/live/forecastability-atlas-v1
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def matched(preds: pd.DataFrame, h: int, start: str) -> pd.DataFrame:
    p = preds[(preds["task"] == "regression") & (preds["horizon"] == h) & (preds["origin"] >= pd.Timestamp(start))]
    a = p[p["model"] == "ridge_A"][["country_iso3", "series_id", "origin", "y", "pred"]]
    b = p[p["model"] == "ridge_B"][["series_id", "origin", "pred"]]
    m = a.merge(b, on=["series_id", "origin"], suffixes=("_a", "_b"))
    m = m[np.isfinite(m["pred_a"]) & np.isfinite(m["pred_b"]) & np.isfinite(m["y"])]
    m["la"] = (m["y"] - m["pred_a"]) ** 2
    m["lb"] = (m["y"] - m["pred_b"]) ** 2
    return m


def dm_one_sided(d: np.ndarray, h: int) -> tuple[float, float, int]:
    T = len(d)
    q = max(h - 1, math.floor(4 * (T / 100) ** (2 / 9)))
    e = d - d.mean()
    var = e @ e / T
    for k in range(1, q + 1):
        var += 2 * (1 - k / (q + 1)) * (e[k:] @ e[:-k]) / T
    stat = d.mean() / math.sqrt(var / T)
    stat *= math.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    return float(stat), float(stats.t.sf(stat, T - 1)), T


def holm(ps: list[float]) -> list[float]:
    order = np.argsort(ps)
    m, out, run = len(ps), [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        out[i] = run
    return out


def main(study_dir: str) -> int:
    root = Path(study_dir)
    res = json.loads((root / "results.json").read_text())
    preds = pd.read_parquet(root / "predictions_primary.parquet")
    start = res["test_start"]
    rows, ps = [], []
    for hyp in res["hypotheses"]:
        h = hyp["hypothesis"]["horizon"]
        m = matched(preds, h, start)
        cm = m.groupby(["origin", "country_iso3"])[["la", "lb"]].mean()
        mm = cm.groupby(level="origin").mean().sort_index()
        ratio = mm["lb"].sum() / mm["la"].sum()
        stat, p, T = dm_one_sided((mm["la"] - mm["lb"]).to_numpy(), h)
        ps.append(p)
        rows.append((hyp, ratio, stat, p, T, m["country_iso3"].nunique(), len(m)))
    adj = holm(ps)
    worst = 0.0
    header = ("hyp", "ratio", "stored", "p_adj", "stored", "T", "countries", "forecasts")
    print("{:4} {:>10} {:>10} {:>10} {:>10} {:>4} {:>9} {:>9}".format(*header))
    for (hyp, ratio, _stat, _p, T, nc, n), pa in zip(rows, adj, strict=True):
        r = hyp["result"]
        worst = max(worst, abs(ratio - r["loss_ratio"]), abs(pa - hyp["p_adjusted"]))
        if (T, nc, n) != (r["n_months"], r["n_countries"], r["n_forecasts"]):
            raise SystemExit(f"sample sizes differ: {(T, nc, n)} vs stored")
        print(
            f"{hyp['hypothesis']['id']:4} {ratio:10.6f} {r['loss_ratio']:10.6f} {pa:10.6f} {hyp['p_adjusted']:10.6f} "
            f"{T:4d} {nc:9d} {n:9d}"
        )
    print(f"maximum absolute discrepancy: {worst:.2e}")
    return 0 if worst < 1e-9 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/studies/live/forecastability-atlas-v1"))
