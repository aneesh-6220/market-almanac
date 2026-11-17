"""Persistence helpers between the analytical engine and the metadata database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from shocktrace.data.identity import commodity_id, market_id, weather_location_id
from shocktrace.data.store import SnapshotManifest
from shocktrace.db import models as m
from shocktrace.experiments.runner import ExperimentOutput, clean_for_json
from shocktrace.providers.base import HealthResult, Provider
from shocktrace.providers.faostat import fao_item_for_commodity


def upsert_sources(s: Session, providers: dict[str, Provider], demo: bool = False) -> None:
    for pid, p in providers.items():
        row = s.get(m.DataSource, pid) or m.DataSource(provider_id=pid)
        i = p.info
        row.name, row.description, row.homepage, row.docs_url = i.name, i.description, i.homepage, i.docs_url
        row.license, row.attribution, row.auth_kind = i.license, i.attribution, i.auth.value
        row.info = i.to_dict()
        row.configured = p.is_configured()
        s.merge(row)


def record_health(s: Session, result: HealthResult) -> None:
    row = s.get(m.DataSource, result.provider_id)
    if row is None:
        return
    row.health_status = result.status.value
    row.health_message = result.message
    row.health_latency_ms = result.latency_ms
    row.health_checked_at = result.checked_at
    row.configured = result.configured
    if result.status.value == "healthy":
        row.last_live_success_at = result.checked_at


def register_snapshot(s: Session, man: SnapshotManifest) -> None:
    s.merge(
        m.DatasetSnapshot(
            snapshot_id=man.snapshot_id,
            dataset=man.dataset,
            mode=man.mode,
            created_at=datetime.fromisoformat(man.created_at),
            row_count=man.row_count,
            content_hash=man.content_hash,
            schema_version=man.schema_version,
            providers=man.providers,
            parent_snapshot_id=man.parent_snapshot_id,
            params=clean_for_json(man.params),
            retrieved_at_min=man.retrieved_at_min,
            retrieved_at_max=man.retrieved_at_max,
            synthetic=man.synthetic,
            warnings=man.warnings,
        )
    )
    for pid in man.providers:
        src = s.get(m.DataSource, pid)
        if src is not None and man.retrieved_at_max and not man.synthetic:
            ts = datetime.fromisoformat(man.retrieved_at_max)
            src.last_retrieval_at = ts
            # A non-empty live snapshot is real data returned by the provider's API, so it counts as a
            # live success (fixtures and demo data never reach this branch: they are synthetic or not live).
            if man.mode == "live" and man.row_count > 0 and _later(ts, src.last_live_success_at):
                src.last_live_success_at = ts


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _later(new: datetime, current: datetime | None) -> bool:
    return current is None or _aware(new) > _aware(current)


def backfill_live_success(s: Session) -> None:
    """Derive last_live_success_at from registered live, non-synthetic, non-empty snapshots."""
    snaps = s.scalars(
        select(m.DatasetSnapshot).where(
            m.DatasetSnapshot.mode == "live", m.DatasetSnapshot.synthetic.is_(False), m.DatasetSnapshot.row_count > 0
        )
    )
    for snap in snaps:
        if not snap.retrieved_at_max:
            continue
        ts = _aware(datetime.fromisoformat(str(snap.retrieved_at_max)))
        for pid in snap.providers or []:
            src = s.get(m.DataSource, pid)
            if src is not None and _later(ts, src.last_live_success_at):
                src.last_live_success_at = ts


def start_job(
    s: Session, job_id: str, mode: str, provider: str, dataset: str, params: dict[str, Any]
) -> m.IngestionJob:
    job = m.IngestionJob(
        id=job_id,
        mode=mode,
        provider_id=provider,
        dataset=dataset,
        params=clean_for_json(params),
        status="running",
        started_at=datetime.now(UTC),
    )
    s.add(job)
    s.flush()
    return job


def finish_job(
    s: Session,
    job: m.IngestionJob,
    *,
    status: str,
    rows: int | None = None,
    snapshot_id: str | None = None,
    warnings: list[str] | None = None,
    error: str | None = None,
    requests_made: int | None = None,
) -> None:
    job.status, job.rows, job.snapshot_id = status, rows, snapshot_id
    job.warnings = warnings or []
    job.error = error
    job.requests_made = requests_made
    job.finished_at = datetime.now(UTC)


def refresh_reference_entities(s: Session, mode: str, prices: pd.DataFrame, countries: pd.DataFrame) -> None:
    """Rebuild market/commodity/country registries from the current price snapshot."""
    s.execute(delete(m.Market).where(m.Market.mode == mode))
    s.execute(delete(m.Commodity).where(m.Commodity.mode == mode))
    if not prices.empty:
        g = prices.groupby(["provider", "country_iso3", "market_code"])
        for (prov, iso3, code), grp in g:
            last = grp.sort_values("retrieved_at").iloc[-1]
            lat = None if pd.isna(last["lat"]) else float(last["lat"])
            lon = None if pd.isna(last["lon"]) else float(last["lon"])
            s.add(
                m.Market(
                    id=market_id(prov, iso3, code),
                    mode=mode,
                    provider=prov,
                    country_iso3=iso3,
                    market_code=str(code),
                    name=str(last["market_name"]),
                    admin1=None if pd.isna(last["admin1_name"]) else str(last["admin1_name"]),
                    admin2=None if pd.isna(last["admin2_name"]) else str(last["admin2_name"]),
                    lat=lat,
                    lon=lon,
                    weather_location_id=weather_location_id(lat, lon) if lat is not None and lon is not None else None,
                    n_series=int(grp["series_id"].nunique()),
                    first_period=str(grp["period"].min().date()),
                    last_period=str(grp["period"].max().date()),
                )
            )
        for (prov, code), grp in prices.groupby(["provider", "commodity_code"]):
            last = grp.iloc[-1]
            item = fao_item_for_commodity(str(last["commodity_name"]))
            s.add(
                m.Commodity(
                    id=commodity_id(prov, code),
                    mode=mode,
                    provider=prov,
                    code=str(code),
                    name=str(last["commodity_name"]),
                    category=None if pd.isna(last["commodity_category"]) else str(last["commodity_category"]),
                    fao_item_code=item[0] if item else None,
                )
            )
    existing = {c.iso3 for c in s.scalars(select(m.Country).where(m.Country.mode == mode))}
    for r in countries.itertuples():
        s.merge(
            m.Country(
                iso3=r.iso3, mode=mode, name=r.name, region=r.region, income_level=r.income_level, provider=r.provider
            )
        )
        existing.add(r.iso3)
    for iso3 in set(prices["country_iso3"].unique()) - existing if not prices.empty else []:
        s.merge(m.Country(iso3=iso3, mode=mode, name=iso3, region=None, income_level=None, provider="hdx_hapi"))


def save_quality_report(
    s: Session, report_id: str, mode: str, snapshots: dict[str, Any], report: dict[str, Any]
) -> None:
    s.merge(
        m.DataQualityReport(
            id=report_id, mode=mode, snapshot_ids=snapshots, summary=report["summary"], report=clean_for_json(report)
        )
    )


def register_experiment(s: Session, out: ExperimentOutput, artifact_dir: str) -> None:
    r = clean_for_json(out.results)
    eid = out.experiment_id
    s.execute(delete(m.Forecast).where(m.Forecast.experiment_id == eid))
    s.execute(delete(m.ModelComparison).where(m.ModelComparison.experiment_id == eid))
    s.execute(delete(m.ModelEvaluation).where(m.ModelEvaluation.experiment_id == eid))
    s.execute(delete(m.BacktestRun).where(m.BacktestRun.experiment_id == eid))
    s.merge(
        m.Experiment(
            id=eid,
            mode=r["mode"],
            name=r["name"],
            created_at=datetime.fromisoformat(r["created_at"]),
            status=r["status"],
            synthetic=bool(r["synthetic"]),
            country_iso3=r["config"]["country_iso3"],
            commodity_codes=r["config"]["commodity_codes"],
            config=r["config"],
            config_hash=r["config_hash"],
            manifest=r["manifest"],
            verdict=r.get("conclusion", {}).get("verdict"),
            conclusion=r.get("conclusion", {}),
            artifact_dir=artifact_dir,
            n_series=len(r.get("eligible_series", [])),
            warnings=r.get("warnings", []),
        )
    )
    s.flush()
    for t in r.get("tasks", []):
        bid = f"{eid}:{t['task']}:h{t['horizon']}"
        s.add(
            m.BacktestRun(
                id=bid,
                experiment_id=eid,
                task=t["task"],
                horizon=t["horizon"],
                target=t.get("target", ""),
                threshold=t.get("threshold"),
                status=t.get("status", "unknown"),
                n_folds=len(t.get("folds", [])),
                n_test_periods=t.get("n_test_periods"),
                n_test_rows=t.get("n_test_rows"),
                test_start=(t.get("test_period") or [None, None])[0],
                test_end=(t.get("test_period") or [None, None])[1],
                folds=t.get("folds", []),
            )
        )
        s.flush()
        for name, met in t.get("models", {}).items():
            spec = met.get("spec", {})
            s.add(
                m.ModelEvaluation(
                    id=f"{bid}:{name}",
                    backtest_id=bid,
                    experiment_id=eid,
                    model=name,
                    family=spec.get("family"),
                    kind=spec.get("kind", ""),
                    metrics=met,
                )
            )
        for c in t.get("comparisons", []):
            s.add(
                m.ModelComparison(
                    id=f"{bid}:{c['role']}:{c['model_a']}:{c['model_b']}",
                    experiment_id=eid,
                    role=c["role"],
                    task=c["task"],
                    horizon=c["horizon"],
                    threshold=t.get("threshold"),
                    model_a=c["model_a"],
                    model_b=c["model_b"],
                    relative_loss=c.get("relative_loss_b_vs_a"),
                    p_value_b_better=c["dm"].get("p_value_b_better"),
                    verdict=c["verdict"],
                    detail=c,
                )
            )
    for f in r.get("forecasts", []):
        s.add(
            m.Forecast(
                id=f"{eid}:{f['series_id']}:{f['task']}:h{f['horizon']}",
                experiment_id=eid,
                mode=r["mode"],
                series_id=f["series_id"],
                task=f["task"],
                horizon=f["horizon"],
                model=f["model"],
                origin_period=f["origin_period"],
                target_period=f["target_period"],
                information_cutoff=f["information_cutoff"],
                status=f["status"],
                validation_status=f["validation_status"],
                reason=f.get("reason"),
                payload=f,
            )
        )
