from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def fixture_text(provider: str, name: str) -> str:
    return (FIXTURES / provider / name).read_text()


def fixture_json(provider: str, name: str) -> Any:
    return json.loads(fixture_text(provider, name))


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class Recorder:
    """httpx MockTransport that records requests and serves scripted responses."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def make_http(tmp_path: Path):  # type: ignore[no-untyped-def]
    from shocktrace.http import HttpClient, HttpConfig

    def factory(
        handler: Callable[[httpx.Request], httpx.Response], cache: bool = False, retries: int = 2
    ) -> tuple[HttpClient, Recorder, list[float]]:
        rec = Recorder(handler)
        sleeps: list[float] = []

        async def fake_sleep(s: float) -> None:
            sleeps.append(s)

        client = HttpClient(
            HttpConfig(max_retries=retries, backoff_base_seconds=0.01, cache_dir=tmp_path if cache else None),
            transport=rec.transport,
            sleep=fake_sleep,
        )
        return client, rec, sleeps

    return factory


@pytest.fixture
def settings_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from shocktrace.config import Settings, reset_settings_cache

    def factory(**overrides: Any) -> Settings:
        for k in ("HDX_HAPI_APP_IDENTIFIER", "FAOSTAT_ACCESS_TOKEN", "FAOSTAT_USERNAME", "FAOSTAT_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        base = {
            "database_url": f"sqlite:///{tmp_path}/t.db",
            "data_dir": tmp_path / "data",
            "cache_dir": tmp_path / "cache",
            "_env_file": None,
        }
        base.update(overrides)
        reset_settings_cache()
        return Settings(**base)

    return factory


@pytest.fixture(scope="session")
def demo_data() -> dict[str, pd.DataFrame]:
    from shocktrace.data.demo import generate_demo_datasets

    return generate_demo_datasets()


@pytest.fixture(scope="session")
def seeded_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """A fully seeded demo deployment on SQLite (runs the demo experiments once per session)."""
    from shocktrace.config import get_settings, reset_settings_cache

    d = tmp_path_factory.mktemp("seeded")
    env = {
        "DATABASE_URL": f"sqlite:///{d}/api.db",
        "DATA_DIR": str(d / "data"),
        "CACHE_DIR": str(d / "cache"),
        "SHOCKTRACE_MODE": "demo",
        "API_RATE_LIMIT_PER_MINUTE": "100000",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    reset_settings_cache()
    from shocktrace.services import init_db, seed_demo

    s = get_settings()
    init_db(s)
    res = seed_demo(s)
    yield {"settings": s, "seed": res}
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    reset_settings_cache()
