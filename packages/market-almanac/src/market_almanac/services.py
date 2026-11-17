"""Application services shared by the CLI and the API (ingestion, seeding, experiments).

Heavy work (ingestion, model training) runs here from CLI jobs, never inside public HTTP
requests. Each job is idempotent: re-running merges into a new immutable snapshot.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from market_almanac.config import RunMode, Settings
from market_almanac.data.demo import generate_demo_datasets
from market_almanac.data.identity import power_grid_cell, weather_location_id
from market_almanac.data.quality import EligibilityCriteria, assess_prices, build_quality_report
from market_almanac.data.store import DatasetStore, SnapshotManifest
from market_almanac.db import models as m
from market_almanac.db import repository as repo
from market_almanac.db.migrate import migrate, require_current_schema
from market_almanac.db.session import session_scope
from market_almanac.experiments.config import ExperimentConfig
from market_almanac.experiments.runner import ExperimentOutput, run_experiment, save_experiment
from market_almanac.geo.spam import packaged_weights
from market_almanac.logging import get_logger, log_event
from market_almanac.providers import build_providers
from market_almanac.providers.base import HealthResult, ProviderError
from market_almanac.providers.faostat import fao_item_for_commodity
from market_almanac.providers.imf import SERIES as IMF_SERIES
from market_almanac.providers.world_bank import INDICATORS as WB_INDICATORS

log = get_logger("services")
DATASETS = ("prices", "weather_monthly", "macro", "agriculture", "countries")


def init_db(settings: Settings) -> None:
    """Bring the database to the latest schema (Alembic; idempotent, also upgrades v0.1 databases)."""
    migrate(settings.database_url)


def store_for(settings: Settings) -> DatasetStore:
    return DatasetStore(settings.lake_dir, settings.market_almanac_mode.value)


def default_experiment_name(settings: Settings, country: str, commodities: list[str]) -> str:
    """Human-readable experiment name from stored metadata, e.g. 'Burkina Faso: Maize (white)'."""
    import pyarrow.parquet as pq

    store = store_for(settings)
    names: list[str] = []
    country_name = country.upper()
    latest = store.latest("prices")
    if latest:
        t = pq.read_table(
            store.path("prices", latest.snapshot_id), columns=["country_iso3", "commodity_code", "commodity_name"]
        )
        df = t.to_pandas().drop_duplicates()
        df = df[df["country_iso3"] == country.upper()]
        for c in commodities:
            hit = df.loc[df["commodity_code"].astype(str) == str(c), "commodity_name"]
            names.append(str(hit.iloc[0]) if len(hit) else str(c))
    cl = store.latest("countries")
    if cl:
        cdf = store.read("countries", cl.snapshot_id)
        hit = cdf.loc[cdf["iso3"] == country.upper(), "name"] if "iso3" in cdf else pd.Series(dtype=str)
        if len(hit):
            country_name = str(hit.iloc[0])
    return f"{country_name}: {', '.join(names or commodities)}"


class SnapshotMissingError(FileNotFoundError):
    """An experiment's recorded input snapshot is not present in this data lake."""


def load_datasets(
    store: DatasetStore, pinned: dict[str, dict[str, Any]] | None = None
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    """Load the datasets an experiment reads.

    By default the latest snapshot of each dataset. With ``pinned`` (the ``snapshots`` block of
    an experiment manifest) the exact recorded snapshots are loaded instead, so a reproduction
    reads the same bytes as the original run even after newer data has been ingested.
    """
    data, snaps = {}, {}
    for ds in DATASETS:
        latest = store.latest(ds)
        if pinned and ds in pinned:
            want = pinned[ds]["snapshot_id"]
            hit = next((x for x in store.list_snapshots(ds) if x.snapshot_id == want), None)
            if hit is None:
                raise SnapshotMissingError(
                    f"snapshot {want} of dataset '{ds}' is not in this lake; exact reproduction needs the original "
                    "snapshot (import the published data bundle) rather than a fresh download"
                )
            latest = hit
        data[ds] = store.read(ds, latest.snapshot_id if latest else None)
        if latest:
            snaps[ds] = {
                "snapshot_id": latest.snapshot_id,
                "row_count": latest.row_count,
                "content_hash": latest.content_hash,
                "providers": latest.providers,
                "retrieved_at_min": latest.retrieved_at_min,
                "retrieved_at_max": latest.retrieved_at_max,
                "synthetic": latest.synthetic,
            }
    return data, snaps


def _write_and_register(
    settings: Settings,
    store: DatasetStore,
    dataset: str,
    df: pd.DataFrame,
    providers: list[str],
    params: dict[str, Any],
    warnings: list[str],
    merge: bool = True,
    synthetic: bool = False,
    replace_keys_for: dict[str, list[Any]] | None = None,
) -> SnapshotManifest:
    man = store.write(
        dataset,
        df,
        providers=providers,
        params=params,
        merge_with_latest=merge,
        warnings=warnings,
        synthetic=synthetic,
        replace_keys_for=replace_keys_for,
    )
    with session_scope(settings.database_url) as s:
        repo.register_snapshot(s, man)
    return man


def sync_sources(settings: Settings) -> None:
    providers = build_providers(settings)
    with session_scope(settings.database_url) as s:
        repo.upsert_sources(s, providers)


async def check_health(settings: Settings, provider_ids: list[str] | None = None) -> list[HealthResult]:
    providers = build_providers(settings)
    ids = provider_ids or list(providers)
    results = await asyncio.gather(*(providers[i].health_check() for i in ids))
    with session_scope(settings.database_url) as s:
        repo.upsert_sources(s, providers)
        for r in results:
            repo.record_health(s, r)
        repo.backfill_live_success(s)
    return list(results)


@dataclass
class JobOutcome:
    job_id: str
    status: str
    rows: int | None
    snapshot_id: str | None
    warnings: list[str]
    error: str | None = None


async def _run_job(settings: Settings, provider: str, dataset: str, params: dict[str, Any], fn: Any) -> JobOutcome:
    job_id = f"job_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}"
    mode = settings.market_almanac_mode.value
    with session_scope(settings.database_url) as s:
        repo.start_job(s, job_id, mode, provider, dataset, params)
    try:
        rows, snap, warnings, nreq = await fn()
        status, err = "succeeded", None
    except (ProviderError, ValueError, KeyError, OSError) as exc:
        rows, snap, warnings, nreq = None, None, [], None
        status, err = "failed", f"{type(exc).__name__}: {exc}"
        log_event(log, "ingestion job failed", job_id=job_id, provider=provider, error=err)
    except Exception as exc:  # provider HTTP errors and unexpected failures are isolated per job
        rows, snap, warnings, nreq = None, None, [], None
        status, err = "failed", f"{type(exc).__name__}: {exc}"
        log_event(log, "ingestion job failed", job_id=job_id, provider=provider, error=err)
    with session_scope(settings.database_url) as s:
        job = s.get(m.IngestionJob, job_id)
        assert job is not None
        repo.finish_job(
            s, job, status=status, rows=rows, snapshot_id=snap, warnings=warnings, error=err, requests_made=nreq
        )
    return JobOutcome(job_id, status, rows, snap, warnings, err)


def _require_live(settings: Settings) -> None:
    if settings.market_almanac_mode != RunMode.LIVE:
        raise ValueError("ingestion of external data requires MARKET_ALMANAC_MODE=live (demo mode uses synthetic data)")


async def ingest_prices(
    settings: Settings,
    country_iso3: str,
    commodity_codes: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    price_type: str | None = None,
) -> list[JobOutcome]:
    _require_live(settings)
    providers = build_providers(settings)
    hdx = providers["hdx_hapi"]
    store = store_for(settings)
    outcomes = []
    for code in commodity_codes or [None]:  # type: ignore[list-item]
        params = {
            "country_iso3": country_iso3,
            "commodity_code": code,
            "start_date": start_date,
            "end_date": end_date,
            "price_type": price_type,
        }

        async def run(params: dict[str, Any] = params) -> tuple[int, str, list[str], int]:
            res = await hdx.fetch("food_prices", **params)
            man = _write_and_register(settings, store, "prices", res.frame, ["hdx_hapi"], params, res.warnings)
            return len(res.frame), man.snapshot_id, res.warnings, res.requests_made

        outcomes.append(await _run_job(settings, "hdx_hapi", "food_prices", params, run))
    _refresh_registry(settings)
    return outcomes


def _refresh_registry(settings: Settings) -> None:
    store = store_for(settings)
    prices = store.read("prices")
    countries = store.read("countries")
    with session_scope(settings.database_url) as s:
        repo.refresh_reference_entities(s, settings.market_almanac_mode.value, prices, countries)


async def ingest_weather(
    settings: Settings,
    country_iso3: str | None = None,
    series_ids: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    include_production_cells: bool = False,
) -> JobOutcome:
    """Fetch weather for every market cell of a country and, optionally, its crop-production cells.

    Production cells are the NASA POWER cells that carry MapSPAM crop weights for the country
    (``market_almanac.geo.spam.packaged_weights``); they feed the production-region features.
    """
    _require_live(settings)
    store = store_for(settings)
    prices = store.read("prices")
    if country_iso3:
        prices = prices[prices["country_iso3"] == country_iso3]
    if series_ids:
        prices = prices[prices["series_id"].isin(series_ids)]
    coords = prices.dropna(subset=["lat", "lon"]).drop_duplicates(["lat", "lon"])[["lat", "lon"]]
    cells: dict[str, tuple[float, float]] = {}
    for r in coords.itertuples():
        cells.setdefault(weather_location_id(r.lat, r.lon), (float(r.lat), float(r.lon)))
    n_market = len(cells)
    if include_production_cells:
        w = packaged_weights()
        if country_iso3:
            w = w[w["country_iso3"] == country_iso3]
        for r in w.drop_duplicates("location_id").itertuples():
            cells.setdefault(str(r.location_id), (float(r.lat), float(r.lon)))
    providers = build_providers(settings)
    power = providers["nasa_power"]
    params = {
        "country_iso3": country_iso3,
        "cells": len(cells),
        "market_cells": n_market,
        "production_cells_added": len(cells) - n_market,
        "start": str(start),
        "end": str(end),
    }

    async def run() -> tuple[int, str, list[str], int]:
        if not cells:
            raise ValueError("no market coordinates available; ingest prices first")
        results = await asyncio.gather(
            *(power.fetch("weather_monthly", lat=lat, lon=lon, start=start, end=end) for lat, lon in cells.values()),
            return_exceptions=True,
        )
        frames, warnings, nreq = [], [], 0
        for (loc, _), res in zip(cells.items(), results, strict=True):
            if isinstance(res, BaseException):
                warnings.append(f"{loc}: {type(res).__name__}: {res}")
                continue
            frames.append(res.frame)
            nreq += res.requests_made
            warnings.extend(f"{loc}: {w}" for w in res.warnings)
        if not frames:
            raise ValueError("all weather requests failed: " + "; ".join(warnings[:3]))
        df = pd.concat(frames, ignore_index=True)
        man = _write_and_register(settings, store, "weather_monthly", df, ["nasa_power"], params, warnings)
        return len(df), man.snapshot_id, warnings, nreq

    return await _run_job(settings, "nasa_power", "weather_monthly", params, run)


async def ingest_macro(settings: Settings, country_iso3: str, start_period: str = "2005-01") -> list[JobOutcome]:
    _require_live(settings)
    store = store_for(settings)
    providers = build_providers(settings)
    out = []

    async def imf_run() -> tuple[int, str, list[str], int]:
        res = await providers["imf"].fetch("macro_monthly", country_iso3=country_iso3, start_period=start_period)
        if res.frame.empty:
            raise ProviderError("IMF returned no observations for the requested series: " + "; ".join(res.warnings))
        man = _write_and_register(
            settings,
            store,
            "macro",
            res.frame,
            ["imf"],
            {
                "country_iso3": country_iso3,
                "series": [s.code for s in IMF_SERIES],
                "series_status": res.extra.get("series_status"),
            },
            res.warnings,
        )
        return len(res.frame), man.snapshot_id, res.warnings, res.requests_made

    out.append(await _run_job(settings, "imf", "macro_monthly", {"country_iso3": country_iso3}, imf_run))

    async def wb_run() -> tuple[int, str, list[str], int]:
        res = await providers["world_bank"].fetch(
            "indicators", country_iso3=country_iso3, start_year=int(start_period[:4])
        )
        man = _write_and_register(
            settings,
            store,
            "macro",
            res.frame,
            ["world_bank"],
            {"country_iso3": country_iso3, "indicators": [i.code for i in WB_INDICATORS]},
            res.warnings,
        )
        cres = await providers["world_bank"].fetch("countries", country_iso3=country_iso3)
        _write_and_register(
            settings, store, "countries", cres.frame, ["world_bank"], {"country_iso3": country_iso3}, []
        )
        return len(res.frame), man.snapshot_id, res.warnings, res.requests_made + cres.requests_made

    out.append(await _run_job(settings, "world_bank", "indicators", {"country_iso3": country_iso3}, wb_run))
    _refresh_registry(settings)
    return out


async def ingest_agriculture(
    settings: Settings,
    country_iso3: str,
    item_codes: list[str] | None = None,
    start_year: int = 2000,
    use_bulk: bool | None = None,
) -> list[JobOutcome]:
    _require_live(settings)
    store = store_for(settings)
    providers = build_providers(settings)
    fao = providers["faostat"]
    if item_codes is None:
        names = store.read("prices").query("country_iso3 == @country_iso3")["commodity_name"].unique()
        item_codes = sorted({i[0] for n in names if (i := fao_item_for_commodity(str(n)))})
    if use_bulk is None:
        use_bulk = not fao.is_configured()
    dataset = "crop_production_bulk" if use_bulk else "crop_production"
    out = []
    for item in item_codes:
        params = {"country_iso3": country_iso3, "item_code": item, "start_year": start_year, "access": dataset}

        async def run(item: str = item, params: dict[str, Any] = params) -> tuple[int, str, list[str], int]:
            res = await fao.fetch(dataset, country_iso3=country_iso3, item_code=item, start_year=start_year)
            man = _write_and_register(settings, store, "agriculture", res.frame, ["faostat"], params, res.warnings)
            return len(res.frame), man.snapshot_id, res.warnings, res.requests_made

        out.append(await _run_job(settings, "faostat", dataset, params, run))
    return out


def run_quality(settings: Settings) -> dict[str, Any]:
    store = store_for(settings)
    data, snaps = load_datasets(store)
    report = build_quality_report(data)
    report["snapshots"] = snaps
    report["mode"] = settings.market_almanac_mode.value
    report["generated_at"] = datetime.now(UTC).isoformat()
    rid = f"dq_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    report["id"] = rid
    with session_scope(settings.database_url) as s:
        repo.save_quality_report(s, rid, settings.market_almanac_mode.value, snaps, report)
    return report


def run_and_register(
    settings: Settings,
    cfg: ExperimentConfig,
    experiment_id: str | None = None,
    *,
    loaded: tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]] | None = None,
    extra_datasets: dict[str, pd.DataFrame] | None = None,
    pinned_snapshots: dict[str, dict[str, Any]] | None = None,
) -> ExperimentOutput:
    """Run an experiment on the latest snapshots, save its artefacts and register it.

    ``loaded`` lets a batch reuse datasets it has already read. ``extra_datasets`` adds or
    replaces inputs (used by falsification variants that supply altered production features).
    The schema check runs first so a stale database fails before any work is done.
    """
    require_current_schema(settings.database_url)
    store = store_for(settings)
    data, snaps = loaded if loaded is not None else load_datasets(store, pinned_snapshots)
    if extra_datasets:
        data = {**data, **extra_datasets}
    synthetic = settings.market_almanac_mode == RunMode.DEMO
    out = run_experiment(
        data,
        cfg,
        mode=settings.market_almanac_mode.value,
        snapshots=snaps,
        synthetic=synthetic,
        experiment_id=experiment_id,
    )
    d = save_experiment(out, settings.experiments_dir)
    with session_scope(settings.database_url) as s:
        repo.register_experiment(s, out, str(d))
    return out


DEMO_EXPERIMENTS = (
    ExperimentConfig(
        name="Demoland maize: does local weather help? (SYNTHETIC)", country_iso3="XDM", commodity_codes=["DM-MAIZE"]
    ),
    ExperimentConfig(
        name="Demoland imported rice: negative control (SYNTHETIC)", country_iso3="XDM", commodity_codes=["DM-RICE"]
    ),
)


def seed_demo(settings: Settings, run_experiments: bool = True) -> dict[str, Any]:
    if settings.market_almanac_mode != RunMode.DEMO:
        raise ValueError("demo-seed requires MARKET_ALMANAC_MODE=demo so synthetic data never enters the live lake")
    init_db(settings)
    sync_sources(settings)
    store = store_for(settings)
    data = generate_demo_datasets()
    snaps = {}
    for ds, df in data.items():
        man = _write_and_register(
            settings,
            store,
            ds,
            df,
            ["demo"],
            {"generator": "market_almanac.data.demo", "seed": 20240501},
            ["SYNTHETIC DEMO DATA"],
            merge=False,
            synthetic=True,
        )
        snaps[ds] = man.snapshot_id
        store.prune(ds, keep=2)
    _refresh_registry(settings)
    report = run_quality(settings)
    exps = []
    if run_experiments:
        for i, cfg in enumerate(DEMO_EXPERIMENTS):
            out = run_and_register(settings, cfg, experiment_id=f"demo_{i + 1}_{cfg.commodity_codes[0].lower()}")
            exps.append({"id": out.experiment_id, "verdict": out.results["conclusion"]["verdict"]})
    return {"snapshots": snaps, "quality_report": report["id"], "experiments": exps}


def discover_candidates(prices: pd.DataFrame, criteria: EligibilityCriteria | None = None) -> pd.DataFrame:
    """Rank (country, commodity, unit, price type) groups by the evidence available for forecasting."""
    quality, _ = assess_prices(prices, criteria)
    if not quality:
        return pd.DataFrame()
    q = pd.DataFrame([x.to_dict() for x in quality])
    meta = prices.drop_duplicates("series_id").set_index("series_id")["commodity_code"]
    q["commodity_code"] = q["series_id"].map(meta)
    g = q.groupby(["country_iso3", "commodity_code", "commodity_name", "unit", "price_type", "currency"])
    out = g.agg(
        series=("series_id", "count"),
        eligible_series=("eligible", "sum"),
        median_obs=("n_observations", "median"),
        median_coverage=("coverage", "median"),
        first=("first_period", "min"),
        last=("last_period", "max"),
    ).reset_index()
    out["evidence_score"] = out["eligible_series"] * out["median_obs"] * out["median_coverage"]
    return out.sort_values(["evidence_score", "eligible_series"], ascending=False).reset_index(drop=True)


def experiment_ids(settings: Settings) -> list[str]:
    with session_scope(settings.database_url) as s:
        return list(s.scalars(select(m.Experiment.id).where(m.Experiment.mode == settings.market_almanac_mode.value)))


def load_saved_config(settings: Settings, experiment_id: str) -> ExperimentConfig:
    p = Path(settings.experiments_dir) / experiment_id / "config.json"
    if not p.exists():
        raise FileNotFoundError(f"no saved configuration for experiment {experiment_id}")
    return ExperimentConfig.model_validate_json(p.read_text())


_ = power_grid_cell


def materialize_public(settings: Settings) -> dict[str, Any]:
    """Build the series catalog and coverage inventory for the current snapshots (derived, rebuildable)."""
    from market_almanac.analytics.catalog import build_catalog, coverage_inventory, write_catalog

    store = store_for(settings)
    prices, weather = store.read("prices"), store.read("weather_monthly")
    cat = build_catalog(prices, set(weather["location_id"].dropna().unique()))
    countries = store.read("countries")
    names = dict(zip(countries["iso3"], countries["name"], strict=True)) if len(countries) else {}
    pl, wl = store.latest("prices"), store.latest("weather_monthly")
    source = {
        "prices_snapshot_id": pl.snapshot_id if pl else None,
        "prices_content_hash": pl.content_hash if pl else None,
        "weather_snapshot_id": wl.snapshot_id if wl else None,
    }
    out = write_catalog(cat, coverage_inventory(cat, names), settings.data_dir / "public" / store.mode, source)
    return {"path": str(out), "series": len(cat), "usable": int(cat["usable"].sum()) if len(cat) else 0, **source}


def sync_database(settings: Settings) -> dict[str, Any]:
    """Rebuild the database index from durable artefacts: snapshots, reference entities, experiments, lineage.

    The database holds metadata only; everything in it can be reconstructed from the data lake
    and the experiment directories. This is how a fresh or remote database (for example the
    deployment's PostgreSQL) is brought in line with a set of published artefacts. The job is
    idempotent and never deletes experiment history.
    """
    import json

    import yaml

    require_current_schema(settings.database_url)
    store = store_for(settings)
    mode = settings.market_almanac_mode.value
    sync_sources(settings)
    n_snap = 0
    with session_scope(settings.database_url) as s:
        for ds in DATASETS:
            for man in store.list_snapshots(ds):
                repo.register_snapshot(s, man)
                n_snap += 1
    _refresh_registry(settings)
    registered: list[str] = []
    root = Path(settings.experiments_dir)
    for d in sorted(p for p in root.glob("*") if (p / "results.json").exists()):
        res = json.loads((d / "results.json").read_text())
        if res.get("mode") != mode:
            continue
        out = ExperimentOutput(res["experiment_id"], res, pd.DataFrame(), None, res.get("warnings", []))
        with session_scope(settings.database_url) as s:
            repo.register_experiment(s, out, str(d))
        registered.append(res["experiment_id"])
    applied, skipped = [], []
    lineage = Path(__file__).parent / "research" / "supersessions.yaml"
    for e in yaml.safe_load(lineage.read_text()) or []:
        with session_scope(settings.database_url) as s:
            if s.get(m.Experiment, e["old"]) is None or s.get(m.Experiment, e["new"]) is None:
                skipped.append(e["old"])
                continue
            repo.supersede_experiment(s, e["old"], e["new"], " ".join(str(e["reason"]).split()))
            applied.append(e["old"])
    return {"snapshots": n_snap, "experiments": registered, "superseded": applied, "lineage_skipped": skipped}
