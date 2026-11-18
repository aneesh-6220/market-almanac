"""Audit v1.1, Audit 5: re-execute Atlas v1 groups from the frozen snapshots with the current code.

Unlike ``independent_trace.py`` this deliberately uses the project's own pipeline: the question is
whether the archived predictions are *reproducible* (same inputs + committed code -> same
numbers), not whether the pipeline is correct. The archived run was recorded from a dirty work
tree (``abea5d2``, ``dirty: true`` in 457 of 565 manifests), so a bitwise match at a clean,
committed revision is the evidence that the uncommitted changes did not affect predictions.

    MARKET_ALMANAC_MODE=live uv run python scripts/audit/reexecute_atlas_groups.py \
        --groups ARM_112_KG_R_AMD PSE_55_KG_R_ILS --variants primary weather_time_shift_60

Writes nothing into the study directory; predictions are compared in memory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from market_almanac.config import get_settings
from market_almanac.data.identity import weather_location_id
from market_almanac.experiments.runner import code_provenance, run_experiment
from market_almanac.workbench.data import load_prices
from market_almanac.workbench.execute import (
    VARIANTS,
    _config,
    group_id,
    load_freeze,
    load_weather,
    permute_cells,
    shift_weather,
    studies_dir,
)
from market_almanac.workbench.spec import load_spec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="docs/research/specs/forecastability-atlas-v1.yaml")
    ap.add_argument("--groups", nargs="+", required=True)
    ap.add_argument("--variants", nargs="+", default=["primary"])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    s = get_settings()
    spec = load_spec(Path(a.spec))
    fr = load_freeze(s, spec.id)
    assert fr is not None and fr["spec_hash"] == spec.spec_hash(), "freeze record missing or spec changed"
    groups = [g for g in fr["groups"] if group_id(g) in a.groups]
    pop = load_prices(s, sorted({g["country_iso3"] for g in groups}), pinned=fr["data_snapshots"])
    prices = pop.prices
    mk = prices.dropna(subset=["lat", "lon"]).drop_duplicates(["country_iso3", "market_code"])
    locs = {weather_location_id(x, y) for x, y in zip(mk["lat"], mk["lon"], strict=True) if not (x == 0 and y == 0)}
    # the permutation is defined over ALL study cells, so load weather for every frozen country
    all_c = sorted({g["country_iso3"] for g in fr["groups"]})
    allp = load_prices(s, all_c, pinned=fr["data_snapshots"]).prices
    amk = allp.dropna(subset=["lat", "lon"]).drop_duplicates(["country_iso3", "market_code"])
    alocs = {weather_location_id(x, y) for x, y in zip(amk["lat"], amk["lon"], strict=True) if not (x == 0 and y == 0)}
    weather, _ = load_weather(s, all_c, alocs | locs, pinned=fr["data_snapshots"])
    root = studies_dir(s) / spec.id / "experiments"
    report = {"code": code_provenance(), "rows": []}
    ok = True
    for g in groups:
        gid = group_id(g)
        gp = prices[
            (prices["country_iso3"] == g["country_iso3"])
            & (prices["commodity_code"].astype(str) == str(g["commodity_code"]))
            & (prices["currency"] == g["currency"])
        ]
        gm = gp.dropna(subset=["lat", "lon"]).drop_duplicates("market_code")
        glocs = {
            weather_location_id(x, y) for x, y in zip(gm["lat"], gm["lon"], strict=True) if not (x == 0 and y == 0)
        }
        for v in a.variants:
            tr = VARIANTS[v].get("weather_transform")
            w = (
                weather
                if tr is None
                else shift_weather(weather, 60)
                if tr == "shift60"
                else permute_cells(weather, spec.seed)
            )
            w = w[w["location_id"].isin(glocs)]
            cfg = _config(spec, g, v)
            out = run_experiment(
                {"prices": gp, "weather_monthly": w, "macro": pd.DataFrame(), "agriculture": pd.DataFrame()},
                cfg,
                mode=s.market_almanac_mode.value,
                experiment_id=f"repro__{gid}__{v}",
            )
            new = out.predictions
            old = pd.read_parquet(root / f"{spec.id}__{gid}__{v}" / "predictions.parquet")
            k = ["series_id", "origin", "horizon", "task", "model", "threshold"]
            new = new.sort_values(k, na_position="first").reset_index(drop=True)
            old = old.sort_values(k, na_position="first").reset_index(drop=True)
            same_keys = len(new) == len(old) and bool((new[k[:5]].to_numpy() == old[k[:5]].to_numpy()).all())
            diff = (
                float(np.nanmax(np.abs(new["pred"].to_numpy(float) - old["pred"].to_numpy(float))))
                if same_keys
                else None
            )
            bitwise = same_keys and bool(
                np.array_equal(new["pred"].to_numpy(float), old["pred"].to_numpy(float), equal_nan=True)
            )
            cfg_old = json.loads((root / f"{spec.id}__{gid}__{v}" / "results.json").read_text())["config_hash"]
            row = {
                "group": gid,
                "variant": v,
                "rows": len(new),
                "config_hash_equal": cfg.config_hash() == cfg_old,
                "same_keys": same_keys,
                "max_abs_pred_diff": diff,
                "bitwise_identical": bitwise,
            }
            ok &= bool(row["config_hash_equal"] and bitwise)
            report["rows"].append(row)
            print(json.dumps(row))
    if a.out:
        a.out.write_text(json.dumps(report, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
