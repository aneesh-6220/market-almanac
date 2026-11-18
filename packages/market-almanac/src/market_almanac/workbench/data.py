"""Population selection for research specifications (metadata only; no outcomes are inspected).

Prices come from the country partitions written by global ingestion when they exist, and from
the original research lake otherwise. Every frame returned carries the snapshot identity it was
read from, so the study manifest can cite it and a re-execution can pin it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from market_almanac.data.quality import EligibilityCriteria, assess_prices
from market_almanac.data.store import DatasetStore
from market_almanac.globaldata.partitions import PartitionStore
from market_almanac.workbench.spec import ResearchSpec


@dataclass
class PopulationData:
    prices: pd.DataFrame
    snapshots: dict[str, dict[str, Any]]  # "prices:<ISO3>" -> snapshot identity
    missing: list[str] = field(default_factory=list)  # countries with no stored observations


def load_prices(settings: Any, countries: list[str], pinned: dict[str, dict[str, Any]] | None = None) -> PopulationData:
    mode = settings.market_almanac_mode.value
    pstore = PartitionStore(settings.lake_dir, mode)
    lake = DatasetStore(settings.lake_dir, mode)
    frames, snaps, missing = [], {}, []
    for c in countries:
        key = f"prices:{c}"
        want = (pinned or {}).get(key)
        if (want and want.get("layout") == "partition") or (not want and pstore.latest("prices", c)):
            sid = want["snapshot_id"] if want else pstore.latest("prices", c).snapshot_id  # type: ignore[union-attr]
            man = pstore.get("prices", c, sid)
            frames.append(pstore.read("prices", c, sid, verify=bool(want)))
            snaps[key] = {
                "layout": "partition",
                "dataset": "prices",
                "country_iso3": c,
                "snapshot_id": man.snapshot_id,
                "observation_hash": man.observation_hash,
                "file_sha256": man.file_sha256,
                "row_count": man.row_count,
                "provider": man.provider,
                "retrieved_at_max": man.retrieved_at_max,
            }
            continue
        latest = lake.latest("prices")
        if want:
            sid = want["snapshot_id"]
            if not any(m.snapshot_id == sid for m in lake.list_snapshots("prices")):
                raise FileNotFoundError(f"pinned prices snapshot {sid} is not in this lake")
        elif latest is None:
            missing.append(c)
            continue
        else:
            sid = latest.snapshot_id
        df = pd.read_parquet(lake.path("prices", sid), filters=[("country_iso3", "==", c)])
        if df.empty:
            missing.append(c)
            continue
        frames.append(df)
        man0 = next(m for m in lake.list_snapshots("prices") if m.snapshot_id == sid)
        snaps[key] = {
            "layout": "lake",
            "dataset": "prices",
            "country_iso3": c,
            "snapshot_id": sid,
            "content_hash": man0.content_hash,
            "row_count": len(df),
        }
    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return PopulationData(prices, snaps, missing)


def criteria_for(spec: ResearchSpec) -> EligibilityCriteria:
    p = spec.population
    return EligibilityCriteria(
        min_observations=p.min_observations,
        min_coverage=p.min_coverage,
        max_gap_months=p.max_gap_months,
        require_coordinates=p.require_coordinates,
    )


def filter_population(prices: pd.DataFrame, spec: ResearchSpec) -> pd.DataFrame:
    p = spec.population
    df = prices[prices["country_iso3"].isin(p.countries) & ~prices["country_iso3"].isin(p.exclude_countries)]
    df = df[df["price_type"].isin(p.price_types)]
    if p.commodity_codes:
        df = df[df["commodity_code"].astype(str).isin(p.commodity_codes)]
    if p.commodity_categories:
        cats = {c.lower() for c in p.commodity_categories}
        df = df[df["commodity_category"].astype(str).str.lower().isin(cats)]
    if p.commodity_name_contains:
        pat = "|".join(s.lower() for s in p.commodity_name_contains)
        df = df[df["commodity_name"].str.lower().str.contains(pat, regex=True, na=False)]
    return df


GROUP_KEYS = ["country_iso3", "commodity_code", "commodity_name", "unit", "price_type", "currency"]


def eligibility_table(prices: pd.DataFrame, spec: ResearchSpec) -> pd.DataFrame:
    """Per-series eligibility (counts, coverage, gaps, coordinates): metadata, not outcomes."""
    df = filter_population(prices, spec)
    frames = []
    for _, g in df.groupby("country_iso3"):
        q, _ = assess_prices(g, criteria_for(spec))
        frames.append(pd.DataFrame([x.to_dict() for x in q]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def select_groups(elig: pd.DataFrame, spec: ResearchSpec) -> pd.DataFrame:
    """Deterministic analysis groups: per country, top groups by eligible series, then commodity code.

    A group is one (country, commodity, unit, price type, currency): series inside a group are
    measured in the same way, so they may be modelled together; different units or currencies
    are never pooled into one group.
    """
    if elig.empty:
        return pd.DataFrame(columns=[*GROUP_KEYS, "eligible_series", "series"])
    g = elig.groupby(GROUP_KEYS).agg(series=("series_id", "count"), eligible_series=("eligible", "sum")).reset_index()
    g = g[g["eligible_series"] >= spec.population.min_eligible_series_per_group]
    g = g.sort_values(["country_iso3", "eligible_series", "commodity_code"], ascending=[True, False, True])
    g = g.groupby("country_iso3").head(spec.population.max_groups_per_country).reset_index(drop=True)
    return g.head(spec.compute.max_groups)


def preview(settings: Any, spec: ResearchSpec) -> dict[str, Any]:
    """What a specification would analyse: counts only, so it can be inspected before freezing."""
    pop = load_prices(settings, [c for c in spec.population.countries if c not in spec.population.exclude_countries])
    elig = eligibility_table(pop.prices, spec) if len(pop.prices) else pd.DataFrame()
    groups = select_groups(elig, spec)
    n_elig = int(elig["eligible"].sum()) if len(elig) else 0
    reasons: dict[str, int] = {}
    if len(elig):
        for rs in elig.loc[~elig["eligible"], "reasons"]:
            for r in rs:
                k = r.split(" (")[0].split(":")[0]
                k = "".join(ch for ch in k if not ch.isdigit()).strip()
                reasons[k] = reasons.get(k, 0) + 1
    return {
        "spec_id": spec.id,
        "spec_hash": spec.spec_hash(),
        "countries_requested": len(spec.population.countries),
        "countries_without_data": pop.missing,
        "series_considered": len(elig),
        "series_eligible": n_elig,
        "exclusion_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "groups": groups.to_dict(orient="records"),
        "n_groups": len(groups),
        "countries_with_groups": int(groups["country_iso3"].nunique()) if len(groups) else 0,
        "series_in_groups": int(groups["eligible_series"].sum()) if len(groups) else 0,
        "snapshots": pop.snapshots,
        "note": "Counts are computed from observation metadata only; no model has been estimated.",
    }
