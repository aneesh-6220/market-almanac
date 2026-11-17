"""Regression: catalog schema validation and deployments with missing or empty data.

Production incident: a deployment whose lake held no price snapshot built an empty catalog without the
``usable`` column, so ``GET /catalog/series`` raised ``KeyError: 'usable'`` (HTTP 500).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from market_almanac.analytics.catalog import (
    CATALOG_REQUIRED_COLUMNS,
    CatalogSchemaError,
    build_catalog,
    validate_catalog,
)


@pytest.fixture
def empty_deployment(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[TestClient]:
    """An API pointed at an empty data directory in the mode given by the test's parametrisation."""
    from market_almanac.config import reset_settings_cache
    from market_almanac_api.deps import cache
    from market_almanac_api.main import create_app

    mode = getattr(request, "param", "demo")
    env = {
        "DATABASE_URL": f"sqlite:///{tmp_path}/api.db",
        "DATA_DIR": str(tmp_path / "data"),
        "CACHE_DIR": str(tmp_path / "cache"),
        "MARKET_ALMANAC_MODE": mode,
        "API_RATE_LIMIT_PER_MINUTE": "100000",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    reset_settings_cache()
    cache._catalog.clear()
    from market_almanac.config import get_settings
    from market_almanac.services import init_db

    init_db(get_settings())
    yield TestClient(create_app(), raise_server_exceptions=False)
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    reset_settings_cache()
    cache._catalog.clear()


def test_empty_catalog_has_full_schema():
    cat = build_catalog(pd.DataFrame())
    assert cat.empty
    assert set(CATALOG_REQUIRED_COLUMNS) <= set(cat.columns)
    assert cat["usable"].dtype == bool
    validate_catalog(cat)  # a genuinely empty catalog is valid


def test_validate_catalog_rejects_missing_usable_column():
    bad = pd.DataFrame({"series_id": ["a"], "country_iso3": ["MLI"]})
    with pytest.raises(CatalogSchemaError, match="usable"):
        validate_catalog(bad)


def test_validate_catalog_accepts_valid_catalog(seeded_env):
    from market_almanac_api.deps import cache

    cat, _, sid = cache.catalog()
    assert sid and len(cat)
    validate_catalog(cat)


@pytest.mark.parametrize("empty_deployment", ["demo"], indirect=True)
def test_empty_demo_catalog_returns_empty_page_not_500(empty_deployment):
    r = empty_deployment.get("/api/v1/catalog/series?q=millet&country=MLI")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [] and body["total"] == 0 and body["snapshot_id"] is None


@pytest.mark.parametrize("empty_deployment", ["live"], indirect=True)
def test_live_deployment_without_data_reports_503(empty_deployment):
    for path in (
        "/api/v1/catalog/series?q=millet&country=MLI",
        "/api/v1/catalog/coverage",
        "/api/v1/catalog/commodities",
        "/api/v1/catalog/markets",
    ):
        r = empty_deployment.get(path)
        assert r.status_code == 503, path
        body = r.json()
        assert body["error"] == "data_unavailable"
        assert "bundle" in body["detail"].lower()
    assert empty_deployment.get("/health").status_code == 200
    assert empty_deployment.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("empty_deployment", ["demo"], indirect=True)
def test_malformed_catalog_reports_503_not_500(empty_deployment, monkeypatch):
    from market_almanac_api import deps

    monkeypatch.setattr(
        "market_almanac.analytics.catalog.build_catalog",
        lambda *a, **k: pd.DataFrame({"series_id": ["x"]}),
    )

    # a snapshot must exist for the catalog to be built; fake the lookup
    class _Snap:
        snapshot_id = "snap"

    monkeypatch.setattr(deps.DatasetStore, "latest", lambda self, ds: _Snap())
    monkeypatch.setattr(deps.DataCache, "frame", lambda self, ds: (pd.DataFrame({"location_id": []}), "snap"))
    r = empty_deployment.get("/api/v1/catalog/series")
    assert r.status_code == 503
    assert r.json()["error"] == "data_unavailable" and "usable" in r.json()["detail"]


def test_valid_catalog_contract_unchanged(seeded_env):
    from market_almanac.config import reset_settings_cache  # noqa: F401
    from market_almanac_api.main import create_app

    c = TestClient(create_app())
    page = c.get("/api/v1/catalog/series?limit=3").json()
    assert set(page) >= {"items", "total", "limit", "offset", "snapshot_id", "synthetic"}
    assert page["items"] and page["items"][0]["usable"] is True


@pytest.mark.parametrize("empty_deployment", ["live"], indirect=True)
def test_bootstrap_requires_checksum_and_reports_failures(empty_deployment, monkeypatch, tmp_path):
    from market_almanac.config import reset_settings_cache
    from market_almanac_api.deps import BootstrapState
    from market_almanac_api.main import _bootstrap_data

    monkeypatch.setenv("DATA_BUNDLE_URL", str(tmp_path / "missing.tar.gz"))
    reset_settings_cache()
    _bootstrap_data()  # no checksum: refused, nothing installed
    assert "DATA_BUNDLE_SHA256" in (BootstrapState.error or "")
    monkeypatch.setenv("DATA_BUNDLE_SHA256", "0" * 64)
    reset_settings_cache()
    _bootstrap_data()  # unreachable bundle: stays up, reports why
    assert BootstrapState.installing is False and "bundle not found" in (BootstrapState.error or "")
    r = empty_deployment.get("/api/v1/catalog/series")
    assert r.status_code == 503 and "bundle not found" in r.json()["detail"]
    BootstrapState.error = None


@pytest.mark.parametrize("empty_deployment", ["demo"], indirect=True)
def test_bootstrap_is_noop_outside_live_mode(empty_deployment, monkeypatch):
    from market_almanac.config import reset_settings_cache
    from market_almanac_api.main import _bootstrap_data

    monkeypatch.setenv("DATA_BUNDLE_URL", "https://example.invalid/x.tar.gz")
    reset_settings_cache()
    _bootstrap_data()


def test_db_indexed_detects_registered_snapshots(seeded_env):
    from market_almanac_api.main import _db_indexed

    assert _db_indexed(seeded_env["settings"]) is True  # seed_demo registers its snapshots


@pytest.mark.parametrize("empty_deployment", ["demo"], indirect=True)
def test_db_indexed_false_for_empty_database(empty_deployment):
    from market_almanac.config import get_settings
    from market_almanac_api.main import _db_indexed

    assert _db_indexed(get_settings()) is False


def test_price_rows_filter_matches_full_frame(seeded_env):
    """The memory-bounded filtered scan returns exactly what filtering the full frame would."""
    from market_almanac_api.deps import cache

    full, _ = cache.frame("prices")
    sid = full["series_id"].iloc[0]
    iso = full["country_iso3"].iloc[0]
    key = ["series_id", "period", "retrieved_at"]
    for kw, col in (({"series_id": sid}, "series_id"), ({"country_iso3": iso}, "country_iso3")):
        exp = full[full[col] == kw[col]].sort_values(key).reset_index(drop=True)
        got = cache.price_rows(**kw).sort_values(key).reset_index(drop=True)
        assert len(got) == len(exp) > 0 and got.equals(exp)
    assert cache.price_rows(series_id="ps_0000000000000000").empty
    assert cache.series_rows(sid).equals(cache.price_rows(series_id=sid))
