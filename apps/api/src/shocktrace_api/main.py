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
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from shocktrace import __version__
from shocktrace.config import get_settings
from shocktrace.logging import configure_logging, get_logger, log_event
from shocktrace_api.routers import data, research, system

log = get_logger("api")


def _warm_caches() -> None:
    """Load the latest quality report and price snapshot so the first user request is fast."""
    from shocktrace.db.session import session_scope
    from shocktrace_api.deps import cache

    s = get_settings()
    try:
        with session_scope(s.database_url) as db:
            cache.quality(db, s.shocktrace_mode.value)
        cache.frame("prices")
        log_event(log, "caches warmed")
    except Exception as exc:  # warming is best-effort; requests load lazily anyway
        log_event(log, "cache warm-up skipped", level=30, error=type(exc).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_warm_caches, name="cache-warm", daemon=True).start()
    yield


DESCRIPTION = """
ShockTrace REST API — *from environmental signals to economic risk*.

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
        title="ShockTrace API",
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

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log_event(log, "unhandled error", level=40, path=request.url.path, error=type(exc).__name__, message=str(exc))
        return JSONResponse({"error": "internal_error", "detail": "An unexpected error occurred."}, status_code=500)

    app.include_router(system.router)
    app.include_router(data.router)
    app.include_router(research.router)
    return app


app = create_app()
