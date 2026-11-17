"""Common provider interface.

Every external source implements :class:`Provider`. Provider-specific parsing stays in
the adapter; the forecasting engine only ever sees canonical frames from
``shocktrace.data.schema``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pandas as pd

from shocktrace.http import HttpClient, ProviderHTTPError


class AuthKind(StrEnum):
    NONE = "none"
    APP_IDENTIFIER = "app_identifier"
    BEARER_TOKEN = "bearer_token"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"  # live request succeeded just now
    DEGRADED = "degraded"  # reachable but returned partial/unexpected data
    UNAVAILABLE = "unavailable"  # network/HTTP failure
    NOT_CONFIGURED = "not_configured"  # credentials missing; no request attempted
    UNKNOWN = "unknown"  # never checked


class ProviderError(Exception):
    """Base class. Messages must be safe to show to end users (no secrets)."""


class ProviderNotConfigured(ProviderError):
    pass


class ProviderSchemaError(ProviderError):
    """Upstream response shape changed or is malformed."""


class ProviderUnavailable(ProviderError):
    pass


class DatasetNotAvailable(ProviderError):
    """A specific dataflow/series is unavailable or discontinued (not substituted)."""


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    description: str
    frequency: str
    spatial_scope: str
    metrics: tuple[str, ...]
    canonical_schema: str


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name: str
    description: str
    homepage: str
    docs_url: str
    license: str
    attribution: str
    auth: AuthKind
    auth_env_vars: tuple[str, ...]
    datasets: tuple[DatasetSpec, ...]
    capabilities: tuple[str, ...]
    caveats: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["auth"] = self.auth.value
        return d


@dataclass
class HealthResult:
    provider_id: str
    status: HealthStatus
    checked_at: datetime
    configured: bool
    latency_ms: float | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "configured": self.configured,
            "latency_ms": self.latency_ms,
            "message": self.message,
        }


@dataclass
class FetchResult:
    provider_id: str
    dataset: str
    frame: pd.DataFrame
    fetched_at: datetime
    params: dict[str, Any]
    source_urls: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_record_count: int = 0
    requests_made: int = 0
    from_cache: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Provider(ABC):
    info: ProviderInfo

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    @property
    def id(self) -> str:
        return self.info.id

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def _probe(self) -> str:
        """Perform a minimal live request; return a short human message."""

    @abstractmethod
    async def fetch(self, dataset: str, **params: Any) -> FetchResult: ...

    def dataset_spec(self, dataset: str) -> DatasetSpec:
        for d in self.info.datasets:
            if d.id == dataset:
                return d
        raise ProviderError(f"{self.id}: unknown dataset '{dataset}'")

    async def health_check(self) -> HealthResult:
        if not self.is_configured():
            return HealthResult(
                self.id,
                HealthStatus.NOT_CONFIGURED,
                utcnow(),
                False,
                message="Credentials not configured: " + ", ".join(self.info.auth_env_vars),
            )
        t0 = time.perf_counter()
        try:
            msg = await self._probe()
            status = HealthStatus.HEALTHY
        except ProviderSchemaError as exc:
            msg, status = f"Reachable but unexpected response: {exc}", HealthStatus.DEGRADED
        except (ProviderHTTPError, ProviderError) as exc:
            msg, status = str(exc), HealthStatus.UNAVAILABLE
        return HealthResult(
            self.id,
            status,
            utcnow(),
            True,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            message=msg,
        )


def require_fields(record: dict[str, Any], fields: tuple[str, ...], provider: str) -> None:
    missing = [f for f in fields if f not in record]
    if missing:
        raise ProviderSchemaError(f"{provider}: upstream record missing expected fields {missing}")
