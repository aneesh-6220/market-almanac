"""Independent source-to-prediction reconstruction for Forecastability Atlas v1 (audit v1.1).

Rebuilds selected analysis groups from the *raw pinned snapshot files* named in the freeze
record, without importing any ``market_almanac`` module:

    raw partition parquet -> identity/series id -> monthly cleaning -> eligibility ->
    price features + target (1-month release lag) -> NASA POWER cell + expanding anomalies ->
    rolling-origin refit schedule -> ridge (own closed form, own median imputation and
    standardisation, own nested validation) -> predictions -> losses

and compares every stage with the archived artefacts (``features.parquet``,
``predictions.parquet``). Only numpy, pandas and hashlib are used.

    uv run python scripts/audit/independent_trace.py \
        --study data/studies/live/forecastability-atlas-v1 --lake data/lake/live \
        --groups ARM_112_KG_R_AMD PSE_55_KG_R_ILS TCD_73_KG_R_XAF NPL_58_KG_R_NPR SEN_73_KG_R_XOF

Exit status is 0 only if every checked quantity agrees within the tolerances printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAG = 1  # protocol section 4: price release lag (months)
HORIZONS = (1, 3)
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
CLIP = 4.0
MIN_CLIM_YEARS = 10
INNER_VAL = 24


# ------------------------------------------------------------------------------------ identity
def series_id(r: pd.Series) -> str:
    f = ("provider", "country_iso3", "market_code", "commodity_code", "unit", "price_type", "price_flag", "currency")
    raw = "|".join("" if pd.isna(r[k]) else str(r[k]).strip().lower() for k in f)
    return "ps_" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def cell(lat: float, lon: float) -> str:
    clat = math.floor(lat / 0.5) * 0.5 + 0.25
    clon = math.floor(lon / 0.625) * 0.625 + 0.3125
    return f"wx_{round(min(clat, 89.75), 4):.4f}_{round(min(clon, 179.6875), 4):.4f}"


# ------------------------------------------------------------------------------------ prices
def monthly(rows: pd.DataFrame) -> dict[str, pd.Series]:
    r = rows.copy()
    fl = r["quality_flags"].fillna("")
    bad = fl.str.contains("invalid_price") | fl.str.contains("duplicate_conflict") | ~(r["price"] > 0)
    r.loc[bad, "price"] = np.nan
    out = {}
    for sid, g in r.groupby("series_id"):
        s = g.groupby("period")["price"].first().sort_index()
        out[sid] = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"))
    return out


def eligible(s: pd.Series) -> bool:
    obs = s.dropna()
    if len(obs) < 48:
        return False
    span = pd.date_range(obs.index.min(), obs.index.max(), freq="MS")
    cov = len(obs) / len(span)
    miss = s.reindex(span).isna().astype(int).to_numpy()
    run = best = 0
    for v in miss:
        run = run + 1 if v else 0
        best = max(best, run)
    return cov >= 0.8 and best <= 6


def price_frame(p: pd.Series) -> pd.DataFrame:
    p = p.reindex(pd.date_range(p.index.min(), p.index.max() + pd.DateOffset(months=LAG), freq="MS"))
    known = p.shift(LAG)
    lp = np.log(known.where(known > 0))
    d1 = lp.diff()
    f = pd.DataFrame(index=p.index)
    f["log_price"] = lp
    f["p_dlog_1"] = d1
    f["p_dlog_3"] = lp - lp.shift(3)
    f["p_dlog_12"] = lp - lp.shift(12)
    f["p_lag_dlog_1"] = d1.shift(1)
    f["p_dev_12"] = lp - lp.rolling(12, min_periods=9).mean()
    f["p_vol_6"] = d1.rolling(6, min_periods=5).std()
    f["m_sin"] = np.sin(2 * np.pi * f.index.month / 12)
    f["m_cos"] = np.cos(2 * np.pi * f.index.month / 12)
    raw = np.log(p.where(p > 0))
    for h in HORIZONS:
        span = h + LAG
        f[f"seasonal_naive_h{h}"] = lp.shift(12 - span) - lp.shift(12)
        f[f"p_seas_hist_h{h}"] = pd.concat(
            [lp.shift(12 * k - span) - lp.shift(12 * k) for k in (1, 2, 3)], axis=1
        ).mean(axis=1)
        f[f"y_h{h}"] = raw.shift(-h) - raw.shift(LAG)  # ln P_{t+h} - ln P_{t-1}
    return f


# ------------------------------------------------------------------------------------ weather
def anomaly(x: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=x.index)
    for m in range(1, 13):
        s = x[x.index.month == m]
        vals = s.to_numpy()
        z = np.full(len(vals), np.nan)
        for i in range(len(vals)):
            prior = vals[:i]
            prior = prior[np.isfinite(prior)]
            # pandas expanding(min_periods) counts non-NaN observations among strictly earlier years
            if len(prior) >= MIN_CLIM_YEARS:
                sd = prior.std(ddof=1)
                if sd > 0:
                    z[i] = np.clip((vals[i] - prior.mean()) / sd, -CLIP, CLIP)
        out.loc[s.index] = z
    return out


def weather_frame(w: pd.DataFrame) -> pd.DataFrame:
    w = w.set_index("period").sort_index()
    w = w.reindex(pd.date_range(w.index.min(), w.index.max(), freq="MS"))
    rain = w["precip_total_mm"]
    f = pd.DataFrame(index=w.index)
    f["w_rain_anom_1"] = anomaly(rain)
    f["w_rain_anom_3"] = anomaly(rain.rolling(3, min_periods=3).sum())
    f["w_rain_anom_6"] = anomaly(rain.rolling(6, min_periods=6).sum())
    f["w_rain_anom_3_lag1"] = f["w_rain_anom_3"].shift(1)
    f["w_rain_anom_3_lag3"] = f["w_rain_anom_3"].shift(3)
    f["w_temp_anom_1"] = anomaly(w["t2m_mean_c"])
    f["w_tmax_anom_3"] = anomaly(w["t2m_max_mean_c"].rolling(3, min_periods=3).mean())
    heat3 = w["heat_days_t2m_max_ge_35c"].rolling(3, min_periods=3).sum()
    f["w_heat_days_3"] = heat3
    f["w_heat_anom_3"] = anomaly(heat3)
    return f


A_COLS = ["p_dlog_1", "p_dlog_3", "p_dlog_12", "p_lag_dlog_1", "p_dev_12", "p_vol_6", "m_sin", "m_cos"]
W_COLS = [
    "w_rain_anom_1",
    "w_rain_anom_3",
    "w_rain_anom_6",
    "w_rain_anom_3_lag1",
    "w_rain_anom_3_lag3",
    "w_temp_anom_1",
    "w_tmax_anom_3",
    "w_heat_days_3",
    "w_heat_anom_3",
]


# ------------------------------------------------------------------------------------ ridge
class Ridge:
    """Median imputation + standardisation (population sd) + closed-form ridge with intercept."""

    def fit(self, X: np.ndarray, y: np.ndarray, alpha: float) -> Ridge:
        # a column with no observed training value is discarded (sklearn SimpleImputer semantics)
        self.keep = ~np.all(np.isnan(X), axis=0)
        X = X[:, self.keep]
        self.med = np.nanmedian(X, axis=0)
        X = np.where(np.isnan(X), self.med, X)
        self.mu, sd = X.mean(0), X.std(0)
        self.sd = np.where(sd == 0, 1.0, sd)
        Z = (X - self.mu) / self.sd
        self.ym = y.mean()
        self.beta = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - self.ym))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = X[:, self.keep]
        X = np.where(np.isnan(X), self.med, X)
        return self.ym + ((X - self.mu) / self.sd) @ self.beta


def fit_select(
    train: pd.DataFrame, cols: list[str], yc: str, h: int, force: float | None = None
) -> tuple[Ridge, float, list[str]]:
    cols = [c for c in cols if train[c].isna().mean() <= 0.5]
    X, y, o = train[cols].to_numpy(float), train[yc].to_numpy(float), train["origin"]
    vs = o.max() - pd.DateOffset(months=INNER_VAL - 1)
    tr = ((o + pd.DateOffset(months=h + LAG)) <= vs).to_numpy()
    va = (o >= vs).to_numpy()
    best = ALPHAS[0] if force is None else force
    if force is None and tr.sum() >= 30 and va.sum() >= 10:
        losses = [np.mean((y[va] - Ridge().fit(X[tr], y[tr], a).predict(X[va])) ** 2) for a in ALPHAS]
        best = ALPHAS[int(np.argmin(losses))]
    return Ridge().fit(X, y, best), best, cols


def backtest(panel: pd.DataFrame, h: int, alpha_mode: str = "nested") -> pd.DataFrame:
    """``alpha_mode``: "nested" (protocol), "B_uses_A" (B gets A's selected penalty), or a number."""
    yc = f"y_h{h}"
    d = panel[panel[yc].notna() & panel["log_price"].notna()].copy()
    o = pd.Series(sorted(d["origin"].unique()))
    first, last = o.iloc[0] + pd.DateOffset(months=48), o.iloc[-1]
    sched = list(pd.date_range(first, last, freq="12MS"))
    out = []
    for k, c in enumerate(sched):
        nxt = sched[k + 1] if k + 1 < len(sched) else d["origin"].max() + pd.DateOffset(months=1)
        train = d[d["origin"] + pd.DateOffset(months=h + LAG) <= c]
        test = d[(d["origin"] >= c) & (d["origin"] < nxt)]
        if test.empty or len(train) < 60:
            continue
        rec = test[["series_id", "origin", yc, f"seasonal_naive_h{h}"]].rename(columns={yc: "y"}).copy()
        rec["naive"] = 0.0
        rec["seasonal_naive"] = rec.pop(f"seasonal_naive_h{h}")
        chosen: dict[str, float] = {}
        for fam, cols in (("A", [*A_COLS, f"p_seas_hist_h{h}"]), ("B", [*A_COLS, f"p_seas_hist_h{h}", *W_COLS])):
            force = None
            if alpha_mode == "B_uses_A" and fam == "B":
                force = chosen["A"]
            elif alpha_mode not in ("nested", "B_uses_A"):
                force = float(alpha_mode)
            m, a, used = fit_select(train, cols, yc, h, force)
            chosen[fam] = a
            rec[f"ridge_{fam}"] = m.predict(test[used].to_numpy(float))
            rec[f"alpha_{fam}"] = a
        rec["refit"] = c
        out.append(rec)
    return pd.concat(out, ignore_index=True)


# ------------------------------------------------------------------------------------ main
def trace(study: Path, lake: Path, gid: str, fr: dict) -> dict:
    def gid_of(x: dict) -> str:
        unit = "".join(ch for ch in str(x["unit"]) if ch.isalnum())[:12] or "u"
        return f"{x['country_iso3']}_{x['commodity_code']}_{unit}_{str(x['price_type'])[:1].upper()}_{x['currency']}"

    g = next(x for x in fr["groups"] if gid_of(x) == gid)
    iso = g["country_iso3"]
    ps = fr["data_snapshots"][f"prices:{iso}"]
    raw_path = lake / "partitions" / "prices" / iso / ps["snapshot_id"] / "data.parquet"
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == ps["file_sha256"], "price snapshot hash mismatch"
    raw = pd.read_parquet(raw_path)
    sel = raw[
        (raw["commodity_code"] == str(g["commodity_code"]))
        & (raw["unit"] == g["unit"])
        & (raw["price_type"] == g["price_type"])
        & (raw["currency"] == g["currency"])
    ]
    rep = {"group": gid, "raw_rows": len(sel)}
    # identity
    ids = sel.apply(series_id, axis=1)
    rep["series_id_recomputed_equal"] = bool((ids == sel["series_id"]).all())
    act = sel[sel["price_flag"] == "actual"]
    act = act[act["lat"].notna() & act["lon"].notna() & ~((act["lat"] == 0) & (act["lon"] == 0))]
    ser = monthly(act)
    mine = sorted(s for s, v in ser.items() if eligible(v))
    exp = study / "experiments" / f"forecastability-atlas-v1__{gid}__primary"
    res = json.loads((exp / "results.json").read_text())
    rep["eligible_mine"], rep["eligible_archived"] = len(mine), len(res["eligible_series"])
    rep["eligible_set_equal"] = mine == sorted(res["eligible_series"])
    # weather
    ws = fr["data_snapshots"][f"weather_monthly:{iso}"]
    wpath = lake / "partitions" / "weather_monthly" / iso / ws["snapshot_id"] / "data.parquet"
    assert hashlib.sha256(wpath.read_bytes()).hexdigest() == ws["file_sha256"], "weather snapshot hash mismatch"
    wx = pd.read_parquet(wpath)
    meta = act.sort_values("retrieved_at").groupby("series_id").last()
    frames, wcache = [], {}
    for sid in mine:
        f = price_frame(ser[sid])
        loc = cell(float(meta.loc[sid, "lat"]), float(meta.loc[sid, "lon"]))
        if loc not in wcache:
            wcache[loc] = weather_frame(wx[wx["location_id"] == loc])
        f = f.join(wcache[loc], how="left")
        f["series_id"], f["location_id"] = sid, loc
        frames.append(f.rename_axis("origin").reset_index())
    panel = pd.concat(frames, ignore_index=True)
    arch = pd.read_parquet(exp / "features.parquet")
    m = panel.merge(arch, on=["series_id", "origin"], suffixes=("", "_arch"))
    rep["feature_rows_mine"], rep["feature_rows_archived"], rep["feature_rows_matched"] = len(panel), len(arch), len(m)
    rep["location_id_equal"] = bool((m["location_id"] == m["location_id_arch"]).all())
    diffs = {}
    for c in [*A_COLS, *W_COLS, "seasonal_naive_h1", "seasonal_naive_h3", "p_seas_hist_h1", "p_seas_hist_h3"]:
        a, b = m[c].to_numpy(float), m[f"{c}_arch"].to_numpy(float)
        both_nan = np.isnan(a) & np.isnan(b)
        diffs[c] = float(np.nanmax(np.abs(a - b))) if (~both_nan).any() else 0.0
        if (np.isnan(a) != np.isnan(b)).any():
            diffs[c] = float("inf")
    for h in HORIZONS:
        a, b = m[f"y_h{h}"].to_numpy(float), m[f"y_dlog_h{h}"].to_numpy(float)
        diffs[f"target_h{h}"] = float("inf") if (np.isnan(a) != np.isnan(b)).any() else float(np.nanmax(np.abs(a - b)))
    rep["max_abs_feature_diff"] = diffs
    # predictions
    ap = pd.read_parquet(exp / "predictions.parquet")
    ap = ap[ap["task"] == "regression"]
    pr = {}
    for h in HORIZONS:
        mine_p = backtest(panel, h)
        q = (
            ap[ap["horizon"] == h]
            .pivot_table(index=["series_id", "origin"], columns="model", values="pred")
            .reset_index()
        )
        yy = ap[ap["horizon"] == h].drop_duplicates(["series_id", "origin"])[["series_id", "origin", "y"]]
        q = q.merge(yy, on=["series_id", "origin"])
        mm = mine_p.merge(q, on=["series_id", "origin"], suffixes=("", "_arch"))
        pr[f"h{h}"] = {
            "rows_mine": len(mine_p),
            "rows_archived": len(q),
            "rows_matched": len(mm),
            "max_abs_y_diff": float(np.max(np.abs(mm["y"] - mm["y_arch"]))),
            **{
                f"max_abs_pred_diff_{k}": float(np.nanmax(np.abs(mm[k] - mm[f"{k}_arch"])))
                for k in ("naive", "seasonal_naive", "ridge_A", "ridge_B")
            },
            "alphas_A": sorted(mine_p["alpha_A"].unique().tolist()),
            "alphas_B": sorted(mine_p["alpha_B"].unique().tolist()),
        }
    rep["predictions"] = pr
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", type=Path, required=True)
    ap.add_argument("--lake", type=Path, required=True)
    ap.add_argument("--groups", nargs="+", required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    fr = json.loads((a.study / "freeze.json").read_text())
    reps = [trace(a.study, a.lake, g, fr) for g in a.groups]
    ok = True
    for r in reps:
        tol_ok = (
            r["series_id_recomputed_equal"]
            and r["eligible_set_equal"]
            and r["location_id_equal"]
            and r["feature_rows_matched"] == r["feature_rows_archived"]
            and max(r["max_abs_feature_diff"].values()) < 1e-9
            and all(
                v["rows_matched"] == v["rows_archived"] == v["rows_mine"]
                and v["max_abs_y_diff"] < 1e-12
                and max(v[k] for k in v if k.startswith("max_abs_pred_diff")) < 1e-6
                for v in r["predictions"].values()
            )
        )
        r["all_checks_pass"] = bool(tol_ok)
        ok &= tol_ok
    print(json.dumps(reps, indent=1, default=str))
    if a.out:
        a.out.write_text(json.dumps(reps, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
