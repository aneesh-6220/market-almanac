"""Descriptive and associational research modes.

Descriptive statistics summarise what prices did; associational models estimate conditional
correlations with stated fixed effects and cluster-robust standard errors. Neither is causal,
and the outputs say so. Missing months stay missing: nothing is interpolated, and month-on-month
changes are computed only between consecutive observed months.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from market_almanac.data.identity import weather_location_id
from market_almanac.data.quality import clean_monthly_series
from market_almanac.features.weather import ClimatologyConfig, weather_features
from market_almanac.workbench.data import GROUP_KEYS, eligibility_table, load_prices, select_groups
from market_almanac.workbench.spec import ResearchSpec

NOT_CAUSAL = (
    "Associational estimate: a conditional correlation under the stated fixed effects. It is not a causal "
    "effect; omitted time-varying factors (conflict, policy, exchange rates, trade) can drive both series."
)


def _series_stats(m: pd.DataFrame) -> dict[str, float | int | None]:
    s = m.set_index("period")["price"].sort_index()
    obs = s.dropna()
    out: dict[str, float | int | None] = {"n_obs": len(obs)}
    if len(obs) < 12:
        return out
    lp = np.log(obs)
    t = (lp.index.year - lp.index.year.min()) + (lp.index.month - 1) / 12
    slope = np.polyfit(np.asarray(t, dtype=float), lp.to_numpy(), 1)[0]
    out["trend_pct_per_year"] = float(np.expm1(slope) * 100)
    d = np.log(s).diff()  # NaN wherever either month is missing: no change across gaps
    out["volatility_sd_dlog"] = float(d.std()) if d.notna().sum() >= 12 else None
    if len(obs) >= 36:
        resid = lp - np.polyval(np.polyfit(np.asarray(t, dtype=float), lp.to_numpy(), 1), np.asarray(t, dtype=float))
        prof = resid.groupby(resid.index.month).mean()
        out["seasonal_amplitude_log"] = float(prof.max() - prof.min()) if len(prof) == 12 else None
        out["seasonal_peak_month"] = int(prof.idxmax()) if len(prof) == 12 else None
    return out


def describe_group(prices: pd.DataFrame) -> dict[str, Any]:
    monthly = clean_monthly_series(prices)
    per = {sid: _series_stats(g) for sid, g in monthly.groupby("series_id")}
    tab = pd.DataFrame.from_dict(per, orient="index")
    lp = monthly.assign(lp=np.log(monthly["price"]))
    disp = lp.groupby("period")["lp"].agg(["std", "count"])
    disp = disp[disp["count"] >= 3]["std"]
    wide = lp.pivot_table(index="period", columns="series_id", values="lp").diff()
    cors = []
    for a, b in itertools.combinations(wide.columns[:40], 2):
        both = wide[[a, b]].dropna()
        if len(both) >= 24:
            cors.append(both[a].corr(both[b]))
    med = tab.median(numeric_only=True).to_dict() if len(tab) else {}
    return {
        "series": len(tab),
        "median_trend_pct_per_year": med.get("trend_pct_per_year"),
        "median_volatility_sd_dlog": med.get("volatility_sd_dlog"),
        "median_seasonal_amplitude_log": med.get("seasonal_amplitude_log"),
        "modal_seasonal_peak_month": int(tab["seasonal_peak_month"].mode().iloc[0])
        if "seasonal_peak_month" in tab and tab["seasonal_peak_month"].notna().any()
        else None,
        "median_cross_market_dispersion_log": float(disp.median()) if len(disp) else None,
        "mean_pairwise_correlation_dlog": float(np.nanmean(cors)) if cors else None,
        "pairs_for_correlation": len(cors),
    }


def run_descriptive(prices: pd.DataFrame, groups: pd.DataFrame, spec: ResearchSpec) -> dict[str, Any]:
    d = spec.descriptive
    assert d is not None
    rows = []
    for g in groups.to_dict(orient="records"):
        sel = prices
        for k in GROUP_KEYS:
            sel = sel[sel[k].astype(str) == str(g[k])]
        if d.period_start:
            sel = sel[sel["period"] >= pd.Timestamp(d.period_start)]
        if d.period_end:
            sel = sel[sel["period"] <= pd.Timestamp(d.period_end)]
        rows.append({**{k: g[k] for k in GROUP_KEYS}, **describe_group(sel)})
    return {"groups": rows, "note": "Nominal local-currency prices; levels are never compared across groups."}


def _panel(prices: pd.DataFrame, weather: pd.DataFrame, spec: ResearchSpec) -> pd.DataFrame:
    a = spec.associational
    assert a is not None
    monthly = clean_monthly_series(prices)
    monthly["dlog"] = monthly.groupby("series_id")["price"].transform(lambda s: np.log(s).diff())
    meta = prices.drop_duplicates("series_id").set_index("series_id")
    monthly["country_iso3"] = monthly["series_id"].map(meta["country_iso3"])
    monthly["location_id"] = [
        weather_location_id(la, lo) if pd.notna(la) and pd.notna(lo) else None
        for la, lo in zip(monthly["series_id"].map(meta["lat"]), monthly["series_id"].map(meta["lon"]), strict=True)
    ]
    clim = ClimatologyConfig("expanding", 1991, 2010, 10)
    feats = []
    for loc, w in weather.groupby("location_id"):
        f = weather_features(w, clim)
        f["location_id"] = loc
        feats.append(f)
    wf = pd.concat(feats, ignore_index=True)
    col = {"rain_anom": "w_rain_anom_1", "t2m_anom": "w_temp_anom_1", "rain_anom_abs": "w_rain_anom_1"}[a.exposure]
    wf["x"] = wf[col].abs() if a.exposure == "rain_anom_abs" else wf[col]
    wf = wf.set_index(["location_id", "period"])["x"]
    for lag in a.exposure_lags:
        shifted = wf.groupby(level=0).shift(lag)
        monthly[f"x_lag{lag}"] = shifted.reindex(
            pd.MultiIndex.from_frame(monthly[["location_id", "period"]])
        ).to_numpy()
    cols = [f"x_lag{lag}" for lag in a.exposure_lags]
    return monthly.dropna(subset=["dlog", *cols])


def fit_panel(panel: pd.DataFrame, spec: ResearchSpec) -> dict[str, Any]:
    """Within-transformed OLS with dummies and cluster-robust covariance (statsmodels)."""
    import statsmodels.api as sm

    a = spec.associational
    assert a is not None
    cols = [f"x_lag{lag}" for lag in a.exposure_lags]
    df = panel.copy()
    y = df["dlog"]
    X = df[cols].copy()
    dummies = []
    if "calendar_month" in a.fixed_effects:
        dummies.append(pd.get_dummies(df["period"].dt.month, prefix="m", drop_first=True, dtype=float))
    if "country_period" in a.fixed_effects:
        cp = df["country_iso3"] + "_" + df["period"].dt.strftime("%Y%m")
        dummies.append(pd.get_dummies(cp, prefix="cp", drop_first=True, dtype=float))
    D = pd.concat(dummies, axis=1) if dummies else pd.DataFrame(index=df.index)
    if "series" in a.fixed_effects:  # absorb series effects by demeaning every regressor within series
        g = df["series_id"]
        y = y - y.groupby(g).transform("mean")
        X = X - X.groupby(g).transform("mean")
        D = D - D.groupby(g).transform("mean") if len(D.columns) else D
    Z = pd.concat([X, D], axis=1)
    if "series" not in a.fixed_effects:
        Z = sm.add_constant(Z)
    if a.standard_errors == "cluster_series":
        groups = pd.factorize(df["series_id"])[0]
    elif a.standard_errors == "cluster_period":
        groups = pd.factorize(df["period"])[0]
    else:
        groups = np.column_stack([pd.factorize(df["series_id"])[0], pd.factorize(df["period"])[0]])
    res = sm.OLS(y.to_numpy(), Z.to_numpy(dtype=float)).fit(cov_type="cluster", cov_kwds={"groups": groups})
    names = list(Z.columns)
    out = []
    ci = res.conf_int(alpha=spec.inference.alpha)
    for i, n in enumerate(names):
        if n in cols:
            out.append(
                {
                    "term": n,
                    "coef": float(res.params[i]),
                    "se": float(res.bse[i]),
                    "p_value": float(res.pvalues[i]),
                    "ci_low": float(ci[i, 0]),
                    "ci_high": float(ci[i, 1]),
                }
            )
    return {
        "terms": out,
        "n_obs": int(res.nobs),
        "n_series": int(df["series_id"].nunique()),
        "n_periods": int(df["period"].nunique()),
        "n_clusters": len(np.unique(groups if groups.ndim == 1 else groups[:, 0])),
        "fixed_effects": a.fixed_effects,
        "standard_errors": a.standard_errors,
        "interpretation": NOT_CAUSAL,
        "units": "coefficient = change in the monthly log price change per one-standard-deviation exposure anomaly",
    }


def execute_other(settings: Any, spec: ResearchSpec) -> dict[str, Any]:
    from market_almanac.workbench.execute import _atomic_json, load_weather, studies_dir
    from market_almanac.workbench.package import write_package

    started = datetime.now(UTC)
    countries = [c for c in spec.population.countries if c not in spec.population.exclude_countries]
    pop = load_prices(settings, countries)
    groups = select_groups(eligibility_table(pop.prices, spec), spec)
    results: dict[str, Any] = {
        "spec_id": spec.id,
        "spec_hash": spec.spec_hash(),
        "title": spec.title,
        "question": spec.question,
        "estimand": spec.estimand,
        "study_type": spec.study_type,
        "evidence_class": spec.evidence_class,
        "data_snapshots": pop.snapshots,
        "groups": groups.to_dict(orient="records"),
    }
    if spec.study_type == "descriptive":
        results["descriptive"] = run_descriptive(pop.prices, groups, spec)
    else:
        sel = pop.prices.merge(groups[GROUP_KEYS], on=GROUP_KEYS)
        xy = sel.dropna(subset=["lat", "lon"]).drop_duplicates("market_code")
        locs = {weather_location_id(a, b) for a, b in zip(xy["lat"], xy["lon"], strict=True)}
        weather, wsn = load_weather(settings, sorted(sel["country_iso3"].unique()), locs)
        results["data_snapshots"].update(wsn)
        if weather.empty:
            results["associational"] = {"status": "insufficient_data", "reason": "no weather stored for these markets"}
        else:
            results["associational"] = {"status": "ok", **fit_panel(_panel(sel, weather, spec), spec)}
    results["limitations"] = [*spec.limitations, spec.timing.vintage_statement]
    results["execution"] = {"started_at": started.isoformat(), "finished_at": datetime.now(UTC).isoformat()}
    root = studies_dir(settings) / spec.id
    _atomic_json(root / "results.json", results)
    write_package(settings, spec, root)
    return results
