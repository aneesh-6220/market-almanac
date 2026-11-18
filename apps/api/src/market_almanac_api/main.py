"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
import weakref
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
from market_almanac_api import resources
from market_almanac_api.deps import DataUnavailableError
from market_almanac_api.routers import coverage, data, global_prices, markets, research, system, workbench

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


def _mark_install_pending() -> None:
    """Flag a pending install before the first request, so it is answered 'installing', not 'missing'."""
    from market_almanac.data.store import DatasetStore
    from market_almanac_api.deps import BootstrapState

    s = get_settings()
    if (
        s.market_almanac_mode.value == "live"
        and s.data_bundle_url
        and s.data_bundle_sha256
        and DatasetStore(s.lake_dir, "live").latest("prices") is None
    ):
        BootstrapState.installing = True


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


def _prices_bootstrap_needed(s: Settings) -> bool:
    """Live deployments install the price artefact when the newest partitions and their catalog are missing."""
    from market_almanac.globaldata.release import is_installed

    return s.market_almanac_mode.value == "live" and s.global_prices_auto_install and not is_installed(s)


def _mark_prices_pending() -> None:
    from market_almanac_api.deps import BootstrapState

    try:
        BootstrapState.prices_installing = _prices_bootstrap_needed(get_settings())
    except Exception:  # an unreadable lake is reported by the install attempt itself
        BootstrapState.prices_installing = True


def _bootstrap_prices() -> None:
    """Install the data-only global price artefact (about 30 MB) so price browsing survives an ephemeral disk."""
    from market_almanac.globaldata.release import install_prices
    from market_almanac_api.deps import BootstrapState, global_prices

    s = get_settings()
    try:
        if not _prices_bootstrap_needed(s):
            return
        BootstrapState.prices_installing, BootstrapState.prices_error = True, None
        log_event(log, "installing global price artefact")
        res = install_prices(s)
        global_prices().invalidate()
        log_event(log, "global price artefact installed", files=res["files"], countries=res["countries"])
    except Exception as exc:  # stay up and answer 503 rather than crash-loop
        BootstrapState.prices_error = f"{type(exc).__name__}: {exc}"[:300]
        log_event(log, "price artefact install failed", level=40, error=BootstrapState.prices_error)
    finally:
        BootstrapState.prices_installing = False


def _startup() -> None:
    _bootstrap_prices()
    _bootstrap_data()
    _warm_caches()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _mark_install_pending()
    _mark_prices_pending()
    threading.Thread(target=_startup, name="data-startup", daemon=True).start()
    resources.start_memory_watch(lambda: dict(INFLIGHT), lambda msg, **kw: log_event(log, msg, level=30, **kw))
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


# Routes that answer without the research data (liveness, readiness and API documentation).
UNGATED_PATHS = frozenset({"/health", "/ready", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
INSTALL_RETRY_AFTER_SECONDS = 30


def readiness(scope: str = "research") -> tuple[str, str | None]:
    """'installing', 'failed' (start-up install refused or failed) or 'ready'.

    ``scope`` is "prices" for the global price layer (installed from the small price artefact) or
    "research" for everything that reads the research bundle (experiments, studies, forecasts).
    """
    from market_almanac_api.deps import BootstrapState

    if scope == "prices":
        if BootstrapState.prices_installing:
            return "installing", None
        if BootstrapState.prices_error:
            return "failed", BootstrapState.prices_error
        return "ready", None
    if BootstrapState.installing:
        return "installing", None
    if BootstrapState.error:
        return "failed", BootstrapState.error
    return "ready", None


# Routes that read only the price artefact (the global explorer and the series pages built on it).
PRICE_SCOPED_PREFIXES = ("/api/v1/global", "/api/v1/series/", "/api/v1/compare")


class InstallGate(BaseHTTPMiddleware):
    """Answer data routes with 503 until the start-up data install has finished.

    Without this gate, routes that read the database or study directories (studies, experiments,
    markets) answered 200 with empty lists or 404 while Render was still installing the bundle,
    which clients and caches cannot tell apart from "this does not exist".
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in UNGATED_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        scope = "prices" if request.url.path.startswith(PRICE_SCOPED_PREFIXES) else "research"
        state, err = readiness(scope)
        if state == "installing":
            what = "price artefact" if scope == "prices" else "research data bundle"
            return JSONResponse(
                {
                    "error": "data_installing",
                    "detail": f"The {what} is being installed on this deployment; retry shortly.",
                },
                status_code=503,
                headers={"Retry-After": str(INSTALL_RETRY_AFTER_SECONDS)},
            )
        if state == "failed":
            return JSONResponse(
                {"error": "data_unavailable", "detail": f"The research data could not be installed: {err}"},
                status_code=503,
                headers={"Retry-After": str(10 * INSTALL_RETRY_AFTER_SECONDS)},
            )
        return await call_next(request)


# Data requests currently executing, by path (read by the memory watch; written only on the event loop).
INFLIGHT: dict[str, int] = {}


class ConcurrencyGate(BaseHTTPMiddleware):
    """Run at most ``limit`` data requests at once; later ones wait in the event loop (no thread, no memory).

    Production showed why: a handful of browsers opening market pages at the same time ran the legacy pandas
    endpoints in parallel and pushed the 512 MiB instance over its limit. ``/health``, ``/ready`` and
    the docs are not gated, so liveness probes never queue behind data work. A request that cannot start within
    ``queue_timeout`` seconds gets 503 with ``Retry-After`` instead of hanging.
    """

    def __init__(self, app: FastAPI, limit: int, queue_timeout: float) -> None:
        super().__init__(app)
        self._limit = max(1, limit)
        self._timeout = queue_timeout
        # One semaphore per event loop: the server has a single loop (so the bound is global), while test clients
        # that start a loop per request must not share one across loops.
        self._slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
            weakref.WeakKeyDictionary()
        )

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        sem = self._slots.get(loop)
        if sem is None:
            sem = self._slots[loop] = asyncio.Semaphore(self._limit)
        return sem

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
            return await call_next(request)
        slots = self._semaphore()
        try:
            await asyncio.wait_for(slots.acquire(), timeout=self._timeout)
        except TimeoutError:
            return JSONResponse(
                {"error": "busy", "detail": "The server is busy with other requests; retry shortly."},
                status_code=503,
                headers={"Retry-After": "5"},
            )
        path = request.url.path
        INFLIGHT[path] = INFLIGHT.get(path, 0) + 1
        try:
            return await call_next(request)
        finally:
            INFLIGHT[path] -= 1
            if not INFLIGHT[path]:
                del INFLIGHT[path]
            slots.release()
            resources.release_heap()


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
    resources.limit_malloc_arenas()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Market Almanac API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=[{"name": n} for n in ("system", "discovery", "data", "research", "output")],
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        ConcurrencyGate,  # type: ignore[arg-type]
        limit=settings.api_max_concurrent_requests,
        queue_timeout=settings.api_queue_timeout_seconds,
    )
    app.add_middleware(RateLimiter, per_minute=settings.api_rate_limit_per_minute)  # type: ignore[arg-type]
    app.add_middleware(InstallGate)
    app.add_middleware(RequestLog)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],  # POST only for specification validation (no execution)
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

    @app.get("/ready", tags=["system"])
    def ready() -> JSONResponse:
        """Readiness: 200 once the price artefact and the research data are usable, else 503 with each part's state."""
        parts = {"prices": readiness("prices"), "research": readiness("research")}
        order = ("failed", "installing", "ready")
        worst = min((st for st, _ in parts.values()), key=order.index)
        detail = {k: err for k, (_, err) in parts.items() if err}
        body: dict[str, object] = {"status": worst, "parts": {k: st for k, (st, _) in parts.items()}}
        if detail:
            body["detail"] = detail
        return JSONResponse(body, status_code=200 if worst == "ready" else 503)

    app.include_router(system.router)
    app.include_router(data.router)
    app.include_router(research.router)
    app.include_router(markets.router)
    app.include_router(coverage.router)
    app.include_router(global_prices.router)
    app.include_router(workbench.router)
    return app


app = create_app()
