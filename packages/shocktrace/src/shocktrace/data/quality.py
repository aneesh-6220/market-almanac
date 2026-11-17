"""Data-quality checks and forecasting-eligibility assessment.

Extreme prices are never removed automatically. Large moves are *flagged* and classified:

* ``corroborated_shock`` – other markets for the same commodity/country moved in the same
  direction in the same month (consistent with a genuine economic shock);
* ``reversing_spike``    – a one-month jump that almost fully reverses the next month while
  no other market moves (a candidate measurement anomaly);
* ``isolated_extreme``   – neither pattern; left for analyst review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

ROBUST_Z_THRESHOLD = 5.0


@dataclass(frozen=True)
class EligibilityCriteria:
    min_observations: int = 48
    min_coverage: float = 0.80  # observed months / months in [first, last]
    max_gap_months: int = 6
    require_coordinates: bool = True  # needed for market-local weather
    max_conflict_share: float = 0.05
    allowed_price_flags: tuple[str, ...] = ("actual",)


@dataclass
class SeriesQuality:
    series_id: str
    country_iso3: str
    market_code: str
    market_name: str
    commodity_code: str
    commodity_name: str
    unit: str
    price_type: str
    currency: str
    price_flag: str
    first_period: str | None
    last_period: str | None
    n_observations: int
    months_spanned: int
    coverage: float
    longest_gap_months: int
    n_conflicting_duplicates: int
    n_invalid_prices: int
    n_extreme_changes: int
    extreme_change_classes: dict[str, int]
    has_coordinates: bool
    eligible: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MIN_SCALE = 0.01  # floor (in log points) so near-constant series still flag large jumps


def _robust_z(x: pd.Series) -> pd.Series:
    med = x.median()
    if not np.isfinite(med):
        return pd.Series(0.0, index=x.index)
    mad = (x - med).abs().median()
    scale = max(1.4826 * mad if np.isfinite(mad) else 0.0, MIN_SCALE)
    return (x - med) / scale


def clean_monthly_series(prices: pd.DataFrame) -> pd.DataFrame:
    """One value per (series, month): conflicting duplicates and invalid prices become NaN.

    Returns a frame with series_id, period, price on a complete monthly index per series
    (missing months are NaN – they are never interpolated).
    """
    p = prices.copy()
    flags = p["quality_flags"].fillna("")
    bad = flags.str.contains("invalid_price") | flags.str.contains("duplicate_conflict") | ~(p["price"] > 0)
    p.loc[bad, "price"] = np.nan
    p = p.groupby(["series_id", "period"], as_index=False)["price"].first()
    out = []
    for sid, g in p.groupby("series_id"):
        g = g.set_index("period").sort_index()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="MS")
        g = g.reindex(idx)
        g.index.name = "period"
        g["series_id"] = sid
        out.append(g.reset_index())
    if not out:
        return pd.DataFrame(columns=["period", "price", "series_id"])
    return pd.concat(out, ignore_index=True)[["series_id", "period", "price"]]


def classify_extremes(monthly: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Flag extreme monthly log changes and classify them (see module docstring)."""
    m = monthly.sort_values(["series_id", "period"]).copy()
    m["dlog"] = m.groupby("series_id")["price"].transform(lambda s: np.log(s).diff())
    m["dlog_next"] = m.groupby("series_id")["dlog"].shift(-1)
    m["z"] = m.groupby("series_id")["dlog"].transform(_robust_z)
    m = m.merge(meta[["series_id", "country_iso3", "commodity_code"]], on="series_id", how="left")
    ext = m[m["z"].abs() > ROBUST_Z_THRESHOLD].copy()
    if ext.empty:
        return ext.assign(classification=pd.Series(dtype="string"), corroborating_markets=pd.Series(dtype="Int64"))
    # cross-market corroboration: same commodity & country, same month, same sign, |dlog| > 0.5*|own|
    peers = m[["series_id", "country_iso3", "commodity_code", "period", "dlog"]]
    keys = ["country_iso3", "commodity_code", "period"]
    wanted = ext[keys].drop_duplicates()
    peer_groups = {k: g for k, g in peers.merge(wanted, on=keys).groupby(keys, dropna=False)}
    empty = peers.iloc[0:0]
    classes, corr = [], []
    for r in ext.itertuples():
        grp = peer_groups.get((r.country_iso3, r.commodity_code, r.period), empty)
        same = grp[grp.series_id != r.series_id]
        n_corr = int(((np.sign(same["dlog"]) == np.sign(r.dlog)) & (same["dlog"].abs() > 0.5 * abs(r.dlog))).sum())
        reverses = (
            pd.notna(r.dlog_next) and np.sign(r.dlog_next) == -np.sign(r.dlog) and abs(r.dlog_next) >= 0.8 * abs(r.dlog)
        )
        if n_corr >= 1:
            classes.append("corroborated_shock")
        elif reverses:
            classes.append("reversing_spike")
        else:
            classes.append("isolated_extreme")
        corr.append(n_corr)
    ext["classification"] = classes
    ext["corroborating_markets"] = corr
    return ext[["series_id", "period", "dlog", "z", "classification", "corroborating_markets"]]


def _longest_gap(s: pd.Series) -> int:
    missing = s.isna().astype(int).to_numpy()
    best = cur = 0
    for v in missing:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return int(best)


def assess_prices(
    prices: pd.DataFrame, criteria: EligibilityCriteria | None = None
) -> tuple[list[SeriesQuality], pd.DataFrame]:
    criteria = criteria or EligibilityCriteria()
    if prices.empty:
        return [], pd.DataFrame()
    meta = prices.sort_values("retrieved_at").groupby("series_id").last().reset_index()
    monthly = clean_monthly_series(prices)
    extremes = classify_extremes(monthly, meta)
    by_monthly = dict(tuple(monthly.groupby("series_id")))
    by_raw = dict(tuple(prices.groupby("series_id")))
    by_ext = dict(tuple(extremes.groupby("series_id"))) if len(extremes) else {}
    results = []
    for r in meta.itertuples():
        g = by_monthly.get(r.series_id, monthly.iloc[0:0])
        raw = by_raw[r.series_id]
        n_obs = int(g["price"].notna().sum())
        span = len(g)
        cov = n_obs / span if span else 0.0
        gap = _longest_gap(g["price"])
        n_conf = int(raw["quality_flags"].fillna("").str.contains("duplicate_conflict").sum())
        n_inv = int(raw["quality_flags"].fillna("").str.contains("invalid_price").sum())
        ex = by_ext.get(r.series_id, extremes.iloc[0:0])
        ex_classes = ex["classification"].value_counts().to_dict() if len(ex) else {}
        has_coords = pd.notna(r.lat) and pd.notna(r.lon) and not (r.lat == 0 and r.lon == 0)
        reasons = []
        if n_obs < criteria.min_observations:
            reasons.append(f"only {n_obs} valid monthly prices (< {criteria.min_observations})")
        if cov < criteria.min_coverage:
            reasons.append(f"coverage {cov:.0%} below {criteria.min_coverage:.0%}")
        if gap > criteria.max_gap_months:
            reasons.append(f"gap of {gap} consecutive missing months (> {criteria.max_gap_months})")
        if criteria.require_coordinates and not has_coords:
            reasons.append("market coordinates missing: no market-local weather proxy possible")
        if span and n_conf / max(len(raw), 1) > criteria.max_conflict_share:
            reasons.append(f"{n_conf} conflicting duplicate records")
        if str(r.price_flag) not in criteria.allowed_price_flags:
            reasons.append(f"price_flag '{r.price_flag}' not in {criteria.allowed_price_flags}")
        results.append(
            SeriesQuality(
                series_id=r.series_id,
                country_iso3=r.country_iso3,
                market_code=str(r.market_code),
                market_name=str(r.market_name),
                commodity_code=str(r.commodity_code),
                commodity_name=str(r.commodity_name),
                unit=str(r.unit),
                price_type=str(r.price_type),
                currency=str(r.currency),
                price_flag=str(r.price_flag),
                first_period=None if g.empty else g["period"].min().date().isoformat(),
                last_period=None if g.empty else g["period"].max().date().isoformat(),
                n_observations=n_obs,
                months_spanned=span,
                coverage=round(cov, 4),
                longest_gap_months=gap,
                n_conflicting_duplicates=n_conf,
                n_invalid_prices=n_inv,
                n_extreme_changes=len(ex),
                extreme_change_classes={k: int(v) for k, v in ex_classes.items()},
                has_coordinates=bool(has_coords),
                eligible=not reasons,
                reasons=reasons,
            )
        )
    return results, extremes


def market_consistency(prices: pd.DataFrame) -> list[str]:
    """Geographic and currency consistency checks across records."""
    issues: list[str] = []
    if prices.empty:
        return issues
    coords = prices.dropna(subset=["lat", "lon"]).groupby(["country_iso3", "market_code"])[["lat", "lon"]].nunique()
    multi = coords[(coords["lat"] > 1) | (coords["lon"] > 1)]
    for (c, m), _ in multi.iterrows():
        issues.append(f"market {c}:{m} reported with multiple coordinates")
    bad = prices[(prices["lat"].abs() > 90) | (prices["lon"].abs() > 180)]
    if len(bad):
        issues.append(f"{len(bad)} records with out-of-range coordinates")
    cur = prices.groupby(["country_iso3", "market_code", "commodity_code", "unit", "price_type"])["currency"].nunique()
    for key, n in cur[cur > 1].items():
        issues.append(f"series {':'.join(map(str, key))} reported in {n} currencies (kept as separate series)")
    badcur = prices[~prices["currency"].fillna("").str.fullmatch(r"[A-Z]{3}")]
    if len(badcur):
        issues.append(f"{len(badcur)} records with non-ISO currency codes")
    units = prices.groupby(["country_iso3", "market_code", "commodity_code", "price_type"])["unit"].nunique()
    for key, n in units[units > 1].items():
        issues.append(f"{':'.join(map(str, key))} reported in {n} units (kept as separate, unmerged series)")
    future = prices[prices["period"] > pd.Timestamp.now().normalize()]
    if len(future):
        issues.append(f"{len(future)} price records dated in the future")
    return issues


def weather_quality(weather: pd.DataFrame) -> dict[str, Any]:
    if weather.empty:
        return {"locations": 0}
    g = weather.groupby("location_id")
    return {
        "locations": int(weather["location_id"].nunique()),
        "months": len(weather),
        "incomplete_months": int((~weather["complete"].fillna(False).astype(bool)).sum()),
        "per_location": {
            k: {
                "first": v["period"].min().date().isoformat(),
                "last": v["period"].max().date().isoformat(),
                "incomplete": int((~v["complete"].fillna(False).astype(bool)).sum()),
            }
            for k, v in g
        },
    }


def build_quality_report(
    datasets: dict[str, pd.DataFrame], criteria: EligibilityCriteria | None = None
) -> dict[str, Any]:
    prices = datasets.get("prices", pd.DataFrame())
    series, extremes = assess_prices(prices, criteria)
    issues = market_consistency(prices)
    report: dict[str, Any] = {
        "criteria": asdict(criteria or EligibilityCriteria()),
        "summary": {
            "price_records": len(prices),
            "series": len(series),
            "eligible_series": sum(s.eligible for s in series),
            "extreme_changes": len(extremes),
            "extreme_change_classes": extremes["classification"].value_counts().to_dict() if len(extremes) else {},
            "consistency_issues": len(issues),
        },
        "consistency_issues": issues,
        "series": [s.to_dict() for s in series],
        "extremes": [
            {**r, "period": pd.Timestamp(r["period"]).date().isoformat()}
            for r in (extremes.to_dict("records") if len(extremes) else [])
        ],
        "weather": weather_quality(datasets.get("weather_monthly", pd.DataFrame())),
    }
    for name in ("macro", "agriculture"):
        df = datasets.get(name, pd.DataFrame())
        if df.empty:
            report[name] = {"records": 0}
            continue
        key = "indicator_code" if name == "macro" else "element_name"
        tcol = "period" if name == "macro" else "year"
        report[name] = {
            "records": len(df),
            "by_indicator": {
                str(k): {"records": len(v), "first": str(v[tcol].min())[:10], "last": str(v[tcol].max())[:10]}
                for k, v in df.groupby(key)
            },
        }
    return report
