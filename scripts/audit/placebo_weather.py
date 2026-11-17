"""Falsification control: time-shifted ("placebo") weather.

For each stored live experiment, re-run the A-vs-B backtest twice on the identical stored panel:
  B_real    : family B with the real market-local weather features (as in the experiment);
  B_placebo : family B where every weather feature at origin t is replaced by the SAME grid cell's
              feature at t - SHIFT months (default 60). Seasonality and marginal distributions are
              preserved, contemporaneous information is destroyed, and no future data is used.
If B_placebo degrades A about as much as B_real, the B-vs-A loss increase is explained by
estimation noise from extra regressors, not by (mis)use of weather information.
Usage: uv run python scripts/audit/placebo_weather.py [SHIFT]
"""

import glob
import json
import sys
from pathlib import Path

import pandas as pd

from shocktrace.data.store import DatasetStore
from shocktrace.evaluation.backtest import BacktestConfig, common_sample, run_backtest
from shocktrace.evaluation.inference import diebold_mariano
from shocktrace.features.weather import WEATHER_FEATURES, ClimatologyConfig, weather_features
from shocktrace.forecasting.models import default_specs
from shocktrace.services import load_datasets

SHIFT = int(sys.argv[1]) if len(sys.argv) > 1 else 60
data, _ = load_datasets(DatasetStore(Path("data/lake/live"), "live"))
w = data["weather_monthly"]
wx = {}
for loc, g in w.groupby("location_id"):
    f = weather_features(g, ClimatologyConfig())
    f["period"] = f["period"] + pd.DateOffset(months=SHIFT)  # value at t = real feature at t-SHIFT
    wx[loc] = f.set_index("period")[list(WEATHER_FEATURES)]

rows = []
for d in sorted(glob.glob("data/experiments/live/exp_*")):
    if d.endswith("_repro"):
        continue
    cfg = json.loads(Path(d, "config.json").read_text())
    panel = pd.read_parquet(Path(d, "features.parquet"))
    plac = []
    for (_sid, loc), g in panel.groupby(["series_id", "location_id"]):
        g = g.copy()
        g[list(WEATHER_FEATURES)] = wx[loc].reindex(g["origin"]).to_numpy()
        plac.append(g)
    placebo = pd.concat(plac)
    specs = {s.name: s for s in default_specs(("A", "B"), include_trees=False)}
    for task, est, tgt in (("regression", "ridge", "y_dlog_h{h}"), ("classification", "logit", "y_spike_h{h}_t10")):
        for h in cfg["horizons"]:
            bc = BacktestConfig(
                h=h,
                target=tgt.format(h=h),
                task=task,
                min_train_months=cfg["min_train_months"],
                refit_every=cfg["refit_every"],
                seed=cfg["seed"],
            )
            real = run_backtest(panel, [specs[f"{est}_A"], specs[f"{est}_B"]], bc).predictions
            plc = run_backtest(placebo, [specs[f"{est}_B"]], bc).predictions.assign(model=f"{est}_Bplacebo")
            allp = pd.concat([real, plc])
            s = common_sample(allp, [f"{est}_A", f"{est}_B", f"{est}_Bplacebo"])
            wide = s.pivot_table(index=["series_id", "origin"], columns="model", values="pred")
            y = s.drop_duplicates(["series_id", "origin"]).set_index(["series_id", "origin"])["y"].reindex(wide.index)
            L = {m: (wide[m] - y) ** 2 for m in wide.columns}
            dates = pd.Series(wide.index.get_level_values("origin"))
            dm = diebold_mariano(
                L[f"{est}_Bplacebo"].reset_index(drop=True), L[f"{est}_B"].reset_index(drop=True), dates, h
            )
            rows.append(
                {
                    "commodity": cfg["commodity_codes"][0],
                    "task": task,
                    "h": h,
                    "n": len(y),
                    "ratio_B_real/A": L[f"{est}_B"].mean() / L[f"{est}_A"].mean(),
                    "ratio_B_placebo/A": L[f"{est}_Bplacebo"].mean() / L[f"{est}_A"].mean(),
                    "DM real-vs-placebo p(two-sided)": dm.p_value_two_sided,
                }
            )
out = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(f"placebo shift = {SHIFT} months")
print(out.round(4).to_string(index=False))
