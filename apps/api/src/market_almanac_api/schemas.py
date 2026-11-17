"""Public API response contracts (stable, versioned under /api/v1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
    snapshot_id: str | None = Field(None, description="Dataset snapshot the rows were read from")
    synthetic: bool = False


class Health(BaseModel):
    status: str
    mode: str
    database: str
    version: str


class SnapshotInfo(BaseModel):
    snapshot_id: str
    dataset: str
    created_at: datetime
    row_count: int
    providers: list[str]
    retrieved_at_min: str | None
    retrieved_at_max: str | None
    synthetic: bool
    content_hash: str


class SourceStatus(BaseModel):
    provider_id: str
    name: str
    description: str
    homepage: str
    docs_url: str
    license: str
    attribution: str
    auth_kind: str
    configured: bool
    health_status: str
    health_message: str | None
    health_checked_at: datetime | None
    health_latency_ms: float | None
    last_live_success_at: datetime | None
    last_retrieval_at: datetime | None
    verification: str = Field(description="live_verified | fixture_tested_only")
    datasets: list[dict[str, Any]]
    caveats: list[str]
    capabilities: list[str]


class Status(BaseModel):
    mode: str
    synthetic: bool
    version: str
    snapshots: list[SnapshotInfo]
    counts: dict[str, int]
    latest_quality_report: dict[str, Any] | None
    sources: list[dict[str, Any]]
    notices: list[str]


class CountryOut(BaseModel):
    iso3: str
    name: str
    region: str | None
    income_level: str | None
    provider: str
    n_markets: int = 0


class CommodityOut(BaseModel):
    id: str
    code: str
    name: str
    category: str | None
    provider: str
    fao_item_code: str | None


class MarketOut(BaseModel):
    id: str
    provider: str
    country_iso3: str
    market_code: str
    name: str
    admin1: str | None
    admin2: str | None
    lat: float | None
    lon: float | None
    weather_location_id: str | None
    n_series: int
    first_period: str | None
    last_period: str | None
    eligible_series: int = 0


class SeriesOut(BaseModel):
    series_id: str
    country_iso3: str
    market_code: str | None = None
    market_name: str
    commodity_code: str | None = None
    commodity_name: str
    unit: str
    price_type: str
    currency: str
    price_flag: str
    first_period: str | None
    last_period: str | None
    n_observations: int
    coverage: float
    longest_gap_months: int
    eligible: bool
    reasons: list[str]
    extreme_change_classes: dict[str, int]
    has_coordinates: bool


class PriceObs(BaseModel):
    series_id: str
    period: str
    price: float | None
    unit: str
    currency: str
    price_type: str
    market_name: str
    commodity_name: str
    quality_flags: str | None
    source_ref: str | None
    retrieved_at: str | None


class WeatherObs(BaseModel):
    location_id: str
    period: str
    precip_total_mm: float | None
    t2m_mean_c: float | None
    t2m_max_mean_c: float | None
    t2m_min_mean_c: float | None
    heat_days_t2m_max_ge_35c: float | None
    complete: bool | None
    rain_anomaly_z: float | None = None
    temp_anomaly_z: float | None = None


class WeatherResponse(BaseModel):
    location_id: str
    lat: float | None
    lon: float | None
    spatial_basis: str
    proxy_warning: str
    climatology: str
    units: dict[str, str]
    snapshot_id: str | None
    synthetic: bool
    items: list[WeatherObs]


class IndicatorObs(BaseModel):
    provider: str
    country_iso3: str
    indicator_code: str
    indicator_name: str
    frequency: str
    period: str
    value: float | None
    unit: str | None
    source_ref: str | None


class AgricultureObs(BaseModel):
    provider: str
    country_iso3: str
    item_code: str
    item_name: str
    element_code: str
    element_name: str
    unit: str
    year: int
    value: float | None
    flag: str | None


class ExperimentSummary(BaseModel):
    id: str
    name: str
    mode: str
    created_at: datetime
    status: str
    synthetic: bool
    country_iso3: str
    commodity_codes: list[str]
    verdict: str | None
    statement: str | None
    n_series: int
    config_hash: str
    evidence_class: str = "exploratory"  # exploratory | confirmatory
    study: str | None = None
    variant: str = "primary"
    method_revision: str | None = None
    price_release_lag_months: int = 0
    superseded_by: str | None = None
    superseded_reason: str | None = None
    current: bool = True  # false when a later run supersedes this one


class BacktestOut(BaseModel):
    id: str
    experiment_id: str
    task: str
    horizon: int
    target: str
    threshold: float | None
    status: str
    n_folds: int
    n_test_periods: int | None
    n_test_rows: int | None
    test_start: str | None
    test_end: str | None


class ComparisonOut(BaseModel):
    id: str
    experiment_id: str
    role: str
    task: str
    horizon: int
    threshold: float | None
    model_a: str
    model_b: str
    relative_loss: float | None
    p_value_b_better: float | None
    verdict: str
    detail: dict[str, Any]


class ForecastOut(BaseModel):
    id: str
    experiment_id: str
    series_id: str
    task: str
    horizon: int
    model: str
    origin_period: str
    target_period: str
    information_cutoff: str
    status: str
    validation_status: str
    reason: str | None
    payload: dict[str, Any]
    synthetic: bool = False


class PredictionPoint(BaseModel):
    series_id: str
    origin: str
    target_period: str
    model: str
    y: float | None
    pred: float | None
    fold: int


class LagCorrelation(BaseModel):
    lag_months: int
    correlation: float | None
    n: int


class LaggedRelationship(BaseModel):
    series_id: str
    weather_variable: str
    target: str
    items: list[LagCorrelation]
    caveat: str


class ErrorOut(BaseModel):
    error: str
    detail: str | None = None
