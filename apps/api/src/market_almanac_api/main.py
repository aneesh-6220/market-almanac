"""FastAPI application factory."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from market_almanac import __version__
from market_almanac.config import Settings, get_settings
from market_almanac.logging import configure_logging, get_logger, log_event
from market_almanac_api.deps import DataUnavailableError
from market_almanac_api.routers import data, markets, research, system

log = get_logger("api")


def _warm_caches() -> None:
    """Load the series catalog so the first user request is fast.

    The data-quality report (~20 MB of JSON, >100 MB as Python objects) and the full price table load on first use.
    """
    from market_almanac_api.deps import cache

    try:
        cache.catalog()  # the full price frame loads on first use (it is ~300 MB at peak)
        log_event(log, "caches warmed")
    except Exception as exc:  # warming is best-effort; requests load lazily anyway
        log_event(log, "cache warm-up skipped", level=30, error=type(exc).__name__)


def _db_indexed(s: Settings) -> bool:
    """True when the database already registers every installed snapshot of this mode."""
    from market_almanac.data.store import DatasetStore
    from market_almanac.db import models as m
    from market_almanac.db.session import session_scope
    from market_almanac.services import DATASETS

    store = DatasetStore(s.lake_dir, s.market_almanac_mode.value)
    installed = {man.snapshot_id for ds in DATASETS for man in store.list_snapshots(ds)}
    with session_scope(s.database_url) as db:
        known = set(
            db.scalars(
                select(m.DatasetSnapshot.snapshot_id).where(m.DatasetSnapshot.mode == s.market_almanac_mode.value)
            )
        )
    return bool(installed) and installed <= known


def _bootstrap_data() -> None:
    """Install the configured research-data bundle when a live deployment has no data (ephemeral disks)."""
    from market_almanac.data.public_bundle import install_bundle
    from market_almanac.data.store import DatasetStore
    from market_almanac.services import init_db, sync_database
    from market_almanac_api.deps import BootstrapState

    s = get_settings()
    if s.market_almanac_mode.value != "live" or not s.data_bundle_url:
        return
    if DatasetStore(s.lake_dir, "live").latest("prices") is not None:
        return
    if not s.data_bundle_sha256:
        BootstrapState.error = "DATA_BUNDLE_SHA256 is required with DATA_BUNDLE_URL"
        log_event(log, "bundle install refused", level=40, error=BootstrapState.error)
        return
    BootstrapState.installing, BootstrapState.error = True, None
    try:
        log_event(log, "installing data bundle")
        res = install_bundle(s.data_bundle_url, s.data_dir, s.data_bundle_sha256)
        init_db(s)
        if _db_indexed(s):
            # the database persists across restarts; re-indexing needs ~600 MB, more than a small host has
            log_event(log, "database already indexed; sync skipped")
        else:
            sync_database(s)
        log_event(log, "data bundle installed", files=res["files"])
    except Exception as exc:  # stay up and report 503 rather than crash-loop
        BootstrapState.error = f"{type(exc).__name__}: {exc}"[:300]
        log_event(log, "bundle install failed", level=40, error=BootstrapState.error)
    finally:
        BootstrapState.installing = False


def _startup() -> None:
    _bootstrap_data()
    _warm_caches()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_startup, name="data-startup", daemon=True).start()
    yield


DESCRIPTION = """
Market Almanac REST API — *from environmental signals to economic risk*.

All endpoints serve cached snapshots and precomputed experiment results; nothing here
triggers outbound requests or model training. Responses carry snapshot IDs and a
`synthetic` flag (true in demo mode). Predictive results are **not causal** estimates.
"""


class RateLimiter(BaseHTTPMiddleware):
    """Sliding-window per-client limiter (in-process; adequate for a single API container)."""

    def __init__(self, app: FastAPI, per_minute: int) -> None:
        super().__init__(app)
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return JSONResponse(
                {"error": "rate_limited", "detail": "Too many requests; retry in a minute."},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        q.append(now)
        return await call_next(request)


class RequestLog(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])[:64]
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        log_event(
            log,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - t0) * 1000, 1),
            request_id=rid,
        )
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Market Almanac API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=[{"name": n} for n in ("system", "discovery", "data", "research", "output")],
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(RateLimiter, per_minute=settings.api_rate_limit_per_minute)  # type: ignore[arg-type]
    app.add_middleware(RequestLog)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "x-request-id"],
    )

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": "http_error", "detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"error": "invalid_request", "detail": errs}, status_code=422)

    @app.exception_handler(DataUnavailableError)
    async def data_unavailable(request: Request, exc: DataUnavailableError) -> JSONResponse:
        log_event(log, "data unavailable", level=30, path=request.url.path, message=str(exc))
        return JSONResponse({"error": "data_unavailable", "detail": str(exc)}, status_code=503)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log_event(log, "unhandled error", level=40, path=request.url.path, error=type(exc).__name__, message=str(exc))
        return JSONResponse({"error": "internal_error", "detail": "An unexpected error occurred."}, status_code=500)

    app.include_router(system.router)
    app.include_router(data.router)
    app.include_router(research.router)
    app.include_router(markets.router)
    return app


app = create_app()
