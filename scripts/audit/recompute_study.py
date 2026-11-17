"""Independently recompute the pooled confirmatory comparisons of sahel-production-weather-v1.

Reads only the stored per-forecast predictions (``predictions.parquet`` of each primary run) and
re-derives, with code that does not import Market Almanac's evaluation module: the common-sample row
count, the loss ratio (MSE of model b / MSE of model a) and a one-sided Diebold-Mariano p-value
(HAC variance with h-1 lags, Harvey-Leybourne-Newbold correction, Student t with T-1 df) on the
equally weighted monthly mean loss differential. Prints stored and recomputed values side by side.

    uv run python scripts/audit/recompute_study.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = "data/experiments/live"
STUDY = f"{ROOT}/studies/sahel-production-weather-v1/results_confirmatory.json"


def recompute(runs: list[str], h: int, a: str, b: str) -> tuple[int, int, float, float]:
    frames = []
    for d in (f"{ROOT}/{r}" for r in runs):
        p = pd.read_parquet(f"{d}/predictions.parquet")
        p = p[(p.task == "regression") & (p.horizon == h) & p.model.isin([a, b])]
        w = p.pivot_table(index=["series_id", "origin"], columns="model", values=["pred", "y"], aggfunc="first")
        w = w.dropna().reset_index()
        frames.append(
            pd.DataFrame(
                {
                    "month": w["origin"].to_numpy(),
                    "la": ((w["y"][a] - w["pred"][a]) ** 2).to_numpy(),
                    "lb": ((w["y"][b] - w["pred"][b]) ** 2).to_numpy(),
                }
            )
        )
    f = pd.concat(frames)
    ratio = float(f.lb.mean() / f.la.mean())
    m = f.groupby("month")[["la", "lb"]].mean()
    d = (m.la - m.lb).to_numpy()
    t = len(d)
    lags = max(h - 1, int(np.floor(4 * (t / 100) ** (2 / 9))))  # protocol: Newey-West, lags >= h-1
    dc = d - d.mean()
    gam = [dc @ dc / t] + [dc[k:] @ dc[:-k] / t for k in range(1, lags + 1)]
    var = (gam[0] + 2 * sum((1 - k / (lags + 1)) * gam[k] for k in range(1, lags + 1))) / t  # Bartlett
    dm = d.mean() / np.sqrt(var)
    hln = dm * np.sqrt((t + 1 - 2 * h + h * (h - 1) / t) / t)
    return len(f), t, ratio, float(1 - stats.t.cdf(hln, df=t - 1))


def main() -> int:
    res = json.loads(Path(STUDY).read_text())
    worst = 0.0
    for row in res["pooled"]:
        if row["variant"] != "primary" or row["contrast"] not in ("P_vs_A", "P_vs_B", "B_vs_A"):
            continue
        runs = [
            e["experiment_id"]
            for e in res["experiments"]
            if e["country"] == row["country"]
            and e["variant"] == "primary"
            and e["evidence_class"] == row["evidence_class"]
            and e["status"] == "completed"
        ]
        n, t, ratio, p = recompute(runs, row["horizon"], row["model_a"], row["model_b"])
        worst = max(worst, abs(ratio - row["loss_ratio"]), abs(p - row["p_b_better"]))
        print(
            f"{row['evidence_class'][:4]} {row['country']} {row['contrast']} h={row['horizon']}: "
            f"stored n={row['n_rows']} T={row['n_months']} "
            f"ratio={row['loss_ratio']:.4f} p={row['p_b_better']:.4f} | recomputed n={n} T={t} "
            f"ratio={ratio:.4f} p={p:.4f}"
        )
    print(f"max absolute discrepancy: {worst:.2e}")
    return 0 if worst < 1e-6 else 1


if __name__ == "__main__":
    sys.exit(main())
