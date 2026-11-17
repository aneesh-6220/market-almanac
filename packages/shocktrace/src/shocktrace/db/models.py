"""SQLAlchemy models: application metadata, registries and analysis results.

Large observation tables live in versioned Parquet snapshots (see ``shocktrace.data.store``);
this database stores what the API needs to list, filter and explain them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class DataSource(Base):
    __tablename__ = "data_sources"
    provider_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    homepage: Mapped[str] = mapped_column(String(300))
    docs_url: Mapped[str] = mapped_column(String(300))
    license: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(Text)
    auth_kind: Mapped[str] = mapped_column(String(32))
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configured: Mapped[bool] = mapped_column(Boolean, default=False)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    health_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    health_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_live_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_retrieval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    provider_id: Mapped[str] = mapped_column(String(32), index=True)
    dataset: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|succeeded|failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests_made: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    row_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(16))
    providers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    parent_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retrieved_at_min: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retrieved_at_max: Mapped[str | None] = mapped_column(String(40), nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)


class Country(Base):
    __tablename__ = "countries"
    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    income_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(32))


class Market(Base):
    __tablename__ = "markets"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # provider:ISO3:market_code
    mode: Mapped[str] = mapped_column(String(8), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    country_iso3: Mapped[str] = mapped_column(String(3), index=True)
    market_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300))
    admin1: Mapped[str | None] = mapped_column(String(300), nullable=True)
    admin2: Mapped[str | None] = mapped_column(String(300), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_location_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    n_series: Mapped[int] = mapped_column(Integer, default=0)
    first_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_period: Mapped[str | None] = mapped_column(String(10), nullable=True)


class Commodity(Base):
    __tablename__ = "commodities"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # provider:code
    mode: Mapped[str] = mapped_column(String(8), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fao_item_code: Mapped[str | None] = mapped_column(String(16), nullable=True)


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    snapshot_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FeatureSet(Base):
    __tablename__ = "feature_sets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    experiment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str] = mapped_column(String(500))
    n_rows: Mapped[int] = mapped_column(Integer)
    columns: Mapped[list[Any]] = mapped_column(JSON, default=list)
    availability: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    status: Mapped[str] = mapped_column(String(32))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    country_iso3: Mapped[str] = mapped_column(String(3), index=True)
    commodity_codes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_hash: Mapped[str] = mapped_column(String(32))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conclusion: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_dir: Mapped[str] = mapped_column(String(500))
    n_series: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Lineage (migration 0002). Rows are never deleted or rewritten when a method changes: the old
    # run points at its replacement and public listings default to runs that are not superseded.
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    superseded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_class: Mapped[str] = mapped_column(String(16), default="exploratory", server_default="exploratory")
    study: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    variant: Mapped[str] = mapped_column(String(32), default="primary", server_default="primary")
    method_revision: Mapped[str | None] = mapped_column(Text, nullable=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # experiment:task:h
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[int] = mapped_column(Integer)
    target: Mapped[str] = mapped_column(String(64))
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    n_folds: Mapped[int] = mapped_column(Integer, default=0)
    n_test_periods: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_test_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    test_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    folds: Mapped[list[Any]] = mapped_column(JSON, default=list)


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"
    id: Mapped[str] = mapped_column(String(140), primary_key=True)
    backtest_id: Mapped[str] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64))
    family: Mapped[str | None] = mapped_column(String(4), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelComparison(Base):
    __tablename__ = "model_comparisons"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    task: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_a: Mapped[str] = mapped_column(String(64))
    model_b: Mapped[str] = mapped_column(String(64))
    relative_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value_b_better: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    series_id: Mapped[str] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(64))
    origin_period: Mapped[str] = mapped_column(String(10))
    target_period: Mapped[str] = mapped_column(String(10))
    information_cutoff: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16))  # issued | withheld
    validation_status: Mapped[str] = mapped_column(String(48))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


Index("ix_forecasts_series_task", Forecast.series_id, Forecast.task, Forecast.horizon)
