"""Independent raw -> feature reconstruction for one market-commodity series (audit evidence).

Recomputes selected features with plain numpy/python from the raw lake records and compares them
with the stored experiment panel. Production feature helpers are deliberately NOT called.
Usage: uv run python scripts/audit/reconstruct_example.py <experiment_dir> <market_name_substring>
"""

import json
import math
import sys
from pathlib import Path

import pandas as pd

from market_almanac.data.store import DatasetStore
from market_almanac.services import load_datasets

exp = Path(sys.argv[1])
market = sys.argv[2] if len(sys.argv) > 2 else "Sankaryare"
cfg = json.loads((exp / "config.json").read_text())
data, _ = load_datasets(DatasetStore(Path("data/lake/live"), "live"))
panel = pd.read_parquet(exp / "features.parquet")
p = data["prices"]
raw = p[(p.country_iso3 == "BFA") & p.commodity_code.isin(cfg["commodity_codes"]) & p.market_name.str.contains(market)]
raw = raw[raw.series_id.isin(panel.series_id.unique())]
sid = raw.series_id.iloc[0]
print(
    "series",
    sid,
    raw[["market_name", "commodity_name", "unit", "price_type", "currency", "price_flag", "lat", "lon"]]
    .iloc[0]
    .to_dict(),
)
print(
    "raw records",
    len(raw),
    "distinct months",
    raw.period.nunique(),
    "duplicate months",
    int(raw.period.duplicated().sum()),
)
flags = raw.quality_flags.fillna("")
print("quality flags", flags.value_counts().to_dict())
price = {r.period: r.price for r in raw.itertuples() if not r.quality_flags or "invalid" not in str(r.quality_flags)}
origin = pd.Timestamp("2024-08-01")


def P(m: int) -> float:
    return price.get(origin + pd.DateOffset(months=m), float("nan"))


lp = {m: math.log(P(m)) for m in range(-15, 4) if not math.isnan(P(m))}
print("raw prices t-12..t+3:", {str((origin + pd.DateOffset(months=m)).date()): P(m) for m in range(-12, 4)})
ind = {
    "p_dlog_1": lp[0] - lp[-1],
    "p_dlog_12": lp[0] - lp[-12],
    "p_dev_12": lp[0] - sum(lp[k] for k in range(-11, 1) if k in lp) / sum(1 for k in range(-11, 1) if k in lp),
    "y_dlog_h1": lp[1] - lp[0],
    "y_dlog_h3": lp[3] - lp[0],
    "y_spike_h1_t10": float(P(1) / P(0) - 1 >= 0.10),
    "y_spike_h3_t10": float(P(3) / P(0) - 1 >= 0.10),
    "seasonal_naive_h1": lp[-11] - lp[-12],
}
# weather: 3-month rainfall total anomaly vs same-calendar-month climatology of prior years only
w = data["weather_monthly"]
row = panel[(panel.series_id == sid) & (panel.origin == origin)].iloc[0]
ww = w[w.location_id == row.location_id].set_index("period").sort_index()
r3 = {}
for y in range(1991, origin.year + 1):
    end = pd.Timestamp(year=y, month=origin.month, day=1)
    months = [end - pd.DateOffset(months=k) for k in range(3)]
    vals = [ww.precip_total_mm.get(m, float("nan")) for m in months]
    r3[y] = sum(vals) if all(not math.isnan(v) for v in vals) else float("nan")
hist = [v for y, v in r3.items() if y < origin.year and not math.isnan(v)]
mu = sum(hist) / len(hist)
sd = math.sqrt(sum((v - mu) ** 2 for v in hist) / (len(hist) - 1))
ind["w_rain_anom_3"] = (r3[origin.year] - mu) / sd
print(
    f"weather cell {row.location_id}: Jun-Aug {origin.year} rain total {r3[origin.year]:.1f} mm; "
    f"climatology {len(hist)} yrs mean {mu:.1f} sd {sd:.1f}"
)
# macro: headline CPI yoy with a 2-month release lag -> uses CPI(t-2) / CPI(t-14)
m = data["macro"]
cpi = m[(m.country_iso3 == "BFA") & (m.indicator_code == "IMF.CPI.ALL")].set_index("period")["value"]
ind["m_cpi_yoy"] = math.log(cpi[origin - pd.DateOffset(months=2)]) - math.log(cpi[origin - pd.DateOffset(months=14)])
print(
    f"CPI {origin - pd.DateOffset(months=2):%Y-%m}={cpi[origin - pd.DateOffset(months=2)]}, "
    f"{origin - pd.DateOffset(months=14):%Y-%m}={cpi[origin - pd.DateOffset(months=14)]}"
)
print(f"\n{'feature':22s} {'independent':>12s} {'pipeline':>12s}  match")
ok = True
for k, v in ind.items():
    pv = float(row[k])
    match = (math.isnan(v) and math.isnan(pv)) or abs(v - pv) < 1e-9
    ok &= match
    print(f"{k:22s} {v:12.6f} {pv:12.6f}  {match}")
print("ALL MATCH" if ok else "MISMATCH")
