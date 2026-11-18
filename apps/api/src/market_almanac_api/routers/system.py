from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from market_almanac import __version__
from market_almanac.config import RunMode, Settings
from market_almanac.db import models as m
from market_almanac.providers import build_providers
from market_almanac_api.deps import cache, db_dep, settings_dep
from market_almanac_api.schemas import Health, SnapshotInfo, SourceStatus, Status

router = APIRouter()


@router.get("/health", response_model=Health, tags=["system"])
def health(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> Health:
    try:
        db.execute(text("SELECT 1"))
        dbs = "ok"
    except Exception:
        dbs = "unavailable"
    return Health(
        status="ok" if dbs == "ok" else "degraded",
        mode=settings.market_almanac_mode.value,
        database=dbs,
        version=__version__,
    )


def _snapshots(db: Session, mode: str) -> list[SnapshotInfo]:
    out = []
    for ds in ("prices", "weather_monthly", "macro", "agriculture", "countries"):
        row = db.scalars(
            select(m.DatasetSnapshot)
            .where(m.DatasetSnapshot.mode == mode, m.DatasetSnapshot.dataset == ds)
            .order_by(desc(m.DatasetSnapshot.created_at))
            .limit(1)
        ).first()
        latest = cache.store().latest(ds)
        if row is None or latest is None:
            continue
        if row.snapshot_id != latest.snapshot_id:  # file store is authoritative for analysis
            row = db.get(m.DatasetSnapshot, latest.snapshot_id) or row
        out.append(
            SnapshotInfo(
                snapshot_id=row.snapshot_id,
                dataset=row.dataset,
                created_at=row.created_at,
                row_count=row.row_count,
                providers=row.providers,
                retrieved_at_min=row.retrieved_at_min,
                retrieved_at_max=row.retrieved_at_max,
                synthetic=row.synthetic,
                content_hash=row.content_hash,
            )
        )
    return out


def _source_out(row: m.DataSource) -> SourceStatus:
    info: dict[str, Any] = row.info or {}
    return SourceStatus(
        provider_id=row.provider_id,
        name=row.name,
        description=row.description,
        homepage=row.homepage,
        docs_url=row.docs_url,
        license=row.license,
        attribution=row.attribution,
        auth_kind=row.auth_kind,
        configured=row.configured,
        health_status=row.health_status,
        health_message=row.health_message,
        health_checked_at=row.health_checked_at,
        health_latency_ms=row.health_latency_ms,
        last_live_success_at=row.last_live_success_at,
        last_retrieval_at=row.last_retrieval_at,
        verification="live_verified" if row.last_live_success_at else "fixture_tested_only",
        datasets=info.get("datasets", []),
        caveats=info.get("caveats", []),
        capabilities=info.get("capabilities", []),
    )


@router.get("/api/v1/sources", response_model=list[SourceStatus], tags=["system"])
def sources(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> list[SourceStatus]:
    rows = {r.provider_id: r for r in db.scalars(select(m.DataSource))}
    if not rows:  # registry not initialised yet: describe providers without health information
        for pid, p in build_providers(settings).items():
            i = p.info
            rows[pid] = m.DataSource(
                provider_id=pid,
                name=i.name,
                description=i.description,
                homepage=i.homepage,
                docs_url=i.docs_url,
                license=i.license,
                attribution=i.attribution,
                auth_kind=i.auth.value,
                info=i.to_dict(),
                configured=p.is_configured(),
                health_status="unknown",
            )
    order = ["hdx_hapi", "nasa_power", "world_bank", "imf", "faostat"]
    return [_source_out(rows[k]) for k in order if k in rows]


@router.get("/api/v1/status", response_model=Status, tags=["system"])
def status(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> Status:
    mode = settings.market_almanac_mode.value
    snaps = _snapshots(db, mode)
    counts = {
        "markets": db.scalar(select(func.count()).select_from(m.Market).where(m.Market.mode == mode)) or 0,
        "commodities": db.scalar(select(func.count()).select_from(m.Commodity).where(m.Commodity.mode == mode)) or 0,
        "countries": db.scalar(select(func.count()).select_from(m.Country).where(m.Country.mode == mode)) or 0,
        "experiments": db.scalar(select(func.count()).select_from(m.Experiment).where(m.Experiment.mode == mode)) or 0,
    }
    # Only the three columns that are returned: the `report` column of a live deployment is a ~20 MB JSON document,
    # and decoding it on every page load (this endpoint is called by all of them) pushed a 512 MiB host over its limit.
    dq = db.execute(
        select(m.DataQualityReport.id, m.DataQualityReport.created_at, m.DataQualityReport.summary)
        .where(m.DataQualityReport.mode == mode)
        .order_by(desc(m.DataQualityReport.created_at))
        .limit(1)
    ).first()
    srcs = [
        {
            "provider_id": s.provider_id,
            "health_status": s.health_status,
            "configured": s.configured,
            "health_checked_at": s.health_checked_at,
            "verification": "live_verified" if s.last_live_success_at else "fixture_tested_only",
        }
        for s in db.scalars(select(m.DataSource))
    ]
    synthetic = settings.market_almanac_mode == RunMode.DEMO
    notices = []
    if synthetic:
        notices.append(
            "DEMO MODE: all data, results and forecasts are SYNTHETIC and describe the fictional 'Demoland'."
        )
    if not snaps:
        notices.append("No datasets have been ingested yet. Run `market-almanac demo-seed` or live ingestion.")
    return Status(
        mode=mode,
        synthetic=synthetic,
        version=__version__,
        snapshots=snaps,
        counts=counts,
        latest_quality_report={"id": dq.id, "created_at": dq.created_at, "summary": dq.summary} if dq else None,
        sources=srcs,
        notices=notices,
    )


@router.get("/api/v1/snapshots", response_model=list[SnapshotInfo], tags=["system"])
def snapshots(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> list[SnapshotInfo]:
    rows = db.scalars(
        select(m.DatasetSnapshot)
        .where(m.DatasetSnapshot.mode == settings.market_almanac_mode.value)
        .order_by(desc(m.DatasetSnapshot.created_at))
        .limit(200)
    )
    return [
        SnapshotInfo(
            snapshot_id=r.snapshot_id,
            dataset=r.dataset,
            created_at=r.created_at,
            row_count=r.row_count,
            providers=r.providers,
            retrieved_at_min=r.retrieved_at_min,
            retrieved_at_max=r.retrieved_at_max,
            synthetic=r.synthetic,
            content_hash=r.content_hash,
        )
        for r in rows
    ]


@router.get("/api/v1/ingestion-jobs", tags=["system"])
def ingestion_jobs(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(m.IngestionJob)
        .where(m.IngestionJob.mode == settings.market_almanac_mode.value)
        .order_by(desc(m.IngestionJob.started_at))
        .limit(100)
    )
    return [
        {
            "id": j.id,
            "provider_id": j.provider_id,
            "dataset": j.dataset,
            "status": j.status,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "rows": j.rows,
            "snapshot_id": j.snapshot_id,
            "requests_made": j.requests_made,
            "warnings": (j.warnings or [])[:10],
            "error": j.error,
            "params": j.params,
        }
        for j in rows
    ]
