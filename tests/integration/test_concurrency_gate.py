"""The API runs only a few data requests at once, so a burst of visitors cannot exhaust a 512 MiB host."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

from market_almanac_api import resources
from market_almanac_api.main import ConcurrencyGate


def _app(limit: int, queue_timeout: float, hold: float) -> tuple[FastAPI, dict[str, int]]:
    state = {"now": 0, "peak": 0}
    guard = threading.Lock()
    app = FastAPI()
    app.add_middleware(ConcurrencyGate, limit=limit, queue_timeout=queue_timeout)  # type: ignore[arg-type]

    @app.get("/api/v1/slow")
    def slow() -> dict[str, bool]:  # sync: runs in the thread pool, like the real data endpoints
        with guard:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(hold)
        with guard:
            state["now"] -= 1
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app, state


def test_never_more_than_the_limit_run_at_once_and_all_requests_are_served():
    app, state = _app(limit=2, queue_timeout=30, hold=0.05)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(lambda _: client.get("/api/v1/slow").status_code, range(24)))
    assert set(codes) == {200}
    assert 1 <= state["peak"] <= 2, state


def test_health_is_never_queued_behind_data_requests():
    app, _ = _app(limit=1, queue_timeout=30, hold=0.4)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=8) as pool:
        busy = [pool.submit(client.get, "/api/v1/slow") for _ in range(6)]
        time.sleep(0.1)
        t = time.perf_counter()
        assert client.get("/health").status_code == 200
        assert time.perf_counter() - t < 0.3  # does not wait for the 6 x 0.4 s of data work
        assert all(f.result().status_code == 200 for f in busy)


def test_a_request_that_cannot_start_in_time_gets_503_with_retry_after():
    app, _ = _app(limit=1, queue_timeout=0.1, hold=0.6)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.get, "/api/v1/slow")
        time.sleep(0.15)
        r = client.get("/api/v1/slow")
        assert r.status_code == 503 and r.headers["retry-after"] == "5" and r.json()["error"] == "busy"
        assert first.result().status_code == 200


def test_heap_release_is_throttled_and_harmless_without_glibc():
    assert resources.release_heap(now=10_000.0) in (True, False)
    assert resources.release_heap(now=10_000.5) is False  # within the throttle window
    assert isinstance(resources.limit_malloc_arenas(), bool)


def test_memory_watch_logs_only_above_the_threshold_with_the_requests_in_flight(monkeypatch):
    seen: list[dict] = []
    reading = {"v": (200.0, 250.0)}
    monkeypatch.setattr(resources, "rss_mb", lambda: reading["v"])
    resources.start_memory_watch(
        lambda: {"/api/v1/status": 2}, lambda msg, **kw: seen.append({"msg": msg, **kw}), 380.0, 0.01
    )
    time.sleep(0.1)
    assert seen == []  # below the threshold: silent
    reading["v"] = (450.4, 470.9)
    time.sleep(0.1)
    assert seen and seen[0] == {
        "msg": "memory high",
        "rss_mb": 450,
        "peak_mb": 471,
        "inflight": {"/api/v1/status": 2},
    }


def test_rss_reading_is_none_or_plausible():
    got = resources.rss_mb()
    assert got is None or 10 < got[0] <= got[1] < 100_000
