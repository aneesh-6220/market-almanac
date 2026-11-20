"""Economic context through the live API: sections, pins, as-of, unavailable states, bounded coverage pages.

A throwaway live deployment over synthetic prices and a synthetic IMF/World Bank world (built by the real refresh
against a scripted server). No network, no production database.
"""

from __future__ import annotations

import csv
import io
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import context_support as cs
from tests.global_support import build_catalog_for, deployment, obs_rows, write_country

STEP = 77  # offset of 2024-06 from 2018-01


def _prices() -> dict[int, float]:
    return {i: 100.0 * 1.003**i * (1.55 if i >= STEP else 1.0) for i in range(105)}


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("eco_api")
    data = root / "data"
    frame = obs_rows(
        country="KEN",
        market=("1", "Alpha", 1.0, 36.0),
        commodity=("10", "Rice (imported)"),
        currency="KES",
        start="2018-01-01",
        months=105,
        prices=_prices(),
    )
    write_country(data, "KEN", frame)
    build_catalog_for(data, ["KEN"])
    return data


def _install(world: Path, tmp: Path) -> str:
    snap = cs.build_snapshot(tmp)
    dest = world / "context" / "live" / snap.snapshot_id
    if not dest.exists():
        shutil.copytree(snap.dir, dest)
    return str(snap.snapshot_id)


def _series_id(c: TestClient) -> str:
    items = c.get("/api/v1/global/countries/KEN/series", params={"limit": 5}).json()["items"]
    return items[0]["series_id"]


@pytest.fixture(scope="module")
def with_context(world: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, str, str]]:
    sid = _install(world, tmp_path_factory.mktemp("ctxsnap"))
    with deployment(world, tmp_path_factory.mktemp("db_with")) as c:
        yield c, _series_id(c), sid
    shutil.rmtree(world / "context", ignore_errors=True)


def _inv(c: TestClient, series: str, **params: Any) -> Any:
    return c.get(f"/api/v1/investigations/{series}", params={"event": "2024-09", **params})


def test_the_investigation_carries_the_economic_context(with_context: Any) -> None:
    c, series, sid = with_context
    r = _inv(c, series)
    assert r.status_code == 200, r.text
    eco = r.json()["context"]["economic"]
    assert eco["status"] == "ok" and eco["snapshot"]["snapshot_id"] == sid and eco["context_id"]
    assert eco["inflation"]["headline"]["state"] == "ok"
    assert eco["exchange_rate"]["applicability"] == "applies"
    assert r.json()["evidence"]["economic"]["propositions"]


def test_the_context_does_not_change_the_investigation_identity_or_v13_results(
    with_context: Any, world: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    c, series, _ = with_context
    a = _inv(c, series).json()
    # a second deployment over the same prices without any context installed
    bare = tmp_path_factory.mktemp("bare")
    shutil.copytree(world, bare / "data", ignore=shutil.ignore_patterns("context"))
    with deployment(bare / "data", tmp_path_factory.mktemp("db_bare")) as c2:
        b = _inv(c2, series).json()
    assert a["config_id"] == b["config_id"] and a["config"] == b["config"]
    for k in ("magnitude", "unusualness", "peers", "breadth", "persistence", "seasonality"):
        assert a[k] == b[k], k
    assert b["context"]["economic"]["status"] == "not_installed" and "economic" not in b["evidence"]


def test_a_pinned_context_is_verified_and_never_silently_ignored(with_context: Any) -> None:
    c, series, sid = with_context
    assert _inv(c, series, context=sid).status_code == 200
    r = _inv(c, series, context="20200101T000000_abcdef")
    assert r.status_code == 409 and sid in r.text


def test_as_of_changes_the_context_identity_only(with_context: Any) -> None:
    c, series, _ = with_context
    now, early = _inv(c, series).json(), _inv(c, series, as_of="2024-09").json()
    assert now["config_id"] == early["config_id"]
    assert now["context"]["economic"]["context_id"] != early["context"]["economic"]["context_id"]
    assert early["context"]["economic"]["inflation"]["headline"]["yoy_pct"] is None
    assert _inv(c, series, as_of="2024-9").status_code == 422


def test_status_endpoint_describes_the_snapshot_and_licences(with_context: Any) -> None:
    c, _, sid = with_context
    s = c.get("/api/v1/context").json()
    assert s["available"] and s["snapshot_id"] == sid
    assert {x["provider"] for x in s["sources"]} >= {"imf", "world_bank"}
    assert all(x["licence"] for x in s["sources"])


def test_coverage_is_paged_filtered_and_bounded(with_context: Any) -> None:
    c, _, _ = with_context
    page = c.get("/api/v1/context/coverage", params={"limit": 2}).json()
    assert page["limit"] == 2 and len(page["items"]) <= 2 and page["total"] >= len(page["items"])
    assert page["summary"]
    one = c.get("/api/v1/context/coverage", params={"country": "KEN"}).json()
    assert {i["country"] for i in one["items"]} == {"KEN"}
    for bad in ({"limit": 101}, {"limit": 0}, {"offset": 1001}, {"country": "ke"}, {"usable": "most"}):
        assert c.get("/api/v1/context/coverage", params=bad).status_code == 422, bad


def test_the_brief_and_exports_carry_the_context(with_context: Any) -> None:
    c, series, sid = with_context
    md = c.get(f"/api/v1/investigations/{series}/export", params={"event": "2024-09", "format": "md"})
    assert md.status_code == 200
    text = md.text
    assert "## Economic context" in text and sid in text
    assert f"context={sid}" in text  # the reproduce link pins the context
    assert text.index("## Economic context") < text.index("## Possible mechanisms")
    js = c.get(f"/api/v1/investigations/{series}/export", params={"event": "2024-09", "format": "json"}).json()
    assert js["context"]["economic"]["snapshot"]["snapshot_id"] == sid
    for table in ("economic_series", "economic_changes", "economic_lags", "economic_lineage", "economic_notes"):
        r = c.get(
            f"/api/v1/investigations/{series}/export", params={"event": "2024-09", "format": "csv", "table": table}
        )
        assert r.status_code == 200, (table, r.text)
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert rows, table


def test_demo_style_unavailable_states_are_explicit(world: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    bare = tmp_path_factory.mktemp("bare_states") / "data"
    shutil.copytree(world, bare, ignore=shutil.ignore_patterns("context"))
    with deployment(bare, tmp_path_factory.mktemp("db_none")) as c:
        s = c.get("/api/v1/context").json()
        assert s["available"] is False and s["status"] == "not_installed"
        assert c.get("/api/v1/context/coverage").status_code == 404
        eco = _inv(c, _series_id(c)).json()["context"]["economic"]
        assert eco["status"] == "not_installed" and eco["reason"]


def test_startup_upgrades_a_metadata_only_snapshot_but_never_refetches_data(
    world: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A metadata-only snapshot is upgraded from the pinned artefact; a snapshot with data is not fetched again."""
    from market_almanac.config import get_settings
    from market_almanac_api import main as api_main

    snap = cs.build_snapshot(tmp_path / "src")
    data = tmp_path / "data"
    dest = data / "context" / "live" / snap.snapshot_id
    shutil.copytree(snap.dir, dest)
    (dest / "observations.parquet").unlink(missing_ok=True)  # metadata only: nothing with data
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("MARKET_ALMANAC_MODE", "live")
    monkeypatch.setenv("CONTEXT_BUNDLE_URL", "https://invalid.example/never-fetched.tar.gz")
    monkeypatch.setenv("CONTEXT_BUNDLE_SHA256", "0" * 64)
    get_settings.cache_clear()
    called: list[str] = []
    monkeypatch.setattr("market_almanac.context.release.install_context", lambda *a, **k: called.append("x") or {})
    try:
        api_main._bootstrap_context()
        assert called == ["x"]  # metadata only: the pinned artefact is installed
        shutil.copyfile(snap.dir / "observations.parquet", dest / "observations.parquet")
        api_main._bootstrap_context()
    finally:
        get_settings.cache_clear()
    assert called == ["x"]  # with data: nothing more is downloaded
