"""The per-series lookup cache that makes a market page cheap on a small server.

A market page asks for the same series from about eight requests. Every uncached lookup opens a DuckDB connection, which
dominated the page's CPU on the 0.1-vCPU free tier. The cache must (1) return exactly what the query returns,
(2) never run the same query twice for concurrent first requests, (3) stay bounded, (4) never hand out a shared object a
caller could corrupt, and (5) follow a new snapshot instead of serving the old one.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from market_almanac.globaldata import prices
from tests.global_support import build_catalog_for, deployment, obs_rows, write_country

G = "/api/v1/global"


@pytest.fixture()
def world(tmp_path: Path) -> Iterator[tuple[TestClient, Path, str]]:
    data = tmp_path / "data"
    frame = pd.concat(
        [
            obs_rows(),
            obs_rows(market=("2", "Beta", 11.0, 21.0), base=120.0, skip={3, 4}),
            obs_rows(
                market=("3", "Gamma", None, None),
                commodity=("30", "Rice"),
                prices={4: -1.0},
                flags={4: "invalid_price"},
                extra=[(9, 777.0, "duplicate_conflict")],
            ),
        ],
        ignore_index=True,
    ).sort_values(["series_id", "period", "price"], kind="stable")
    write_country(data, "TST", frame.reset_index(drop=True))
    build_catalog_for(data)
    with deployment(data, tmp_path) as client:
        yield client, data, frame["series_id"].iloc[0]


def _gp():
    from market_almanac_api.deps import global_prices

    return global_prices()


def test_cached_catalog_rows_equal_the_query_for_every_series(world):
    client, _, _ = world
    gp = _gp()
    ids = [i["series_id"] for i in client.get(f"{G}/countries/TST/series?limit=50&usable_only=false").json()["items"]]
    assert len(ids) == 3
    for sid in ids:
        direct = gp._series_row_query(sid)
        first, second = gp.series_row(sid), gp.series_row(sid)  # the second is a cache hit
        for got in (first, second):
            assert json.dumps(got, sort_keys=True, default=str) == json.dumps(direct, sort_keys=True, default=str)
    # an unknown series is a (cached) miss, never an error
    assert gp.series_row("ps_doesnotexist") is None and gp.series_row("ps_doesnotexist") is None


def test_first_requests_for_a_cold_series_run_each_query_once(world, monkeypatch):
    """Eight panels opening at once must not run the same lookup eight times (a cache stampede)."""
    client, _, sid = world
    gp = _gp()
    gp.invalidate()
    calls: list[str] = []
    real = gp._query

    def counting(sql, params=None):
        calls.append(sql.split("FROM")[0].strip()[:40])
        time.sleep(0.03)  # keep the first lookup in flight while the others arrive
        return real(sql, params)

    monkeypatch.setattr(gp, "_query", counting)
    urls = [
        f"/api/v1/series/{sid}",
        f"/api/v1/series/{sid}/history",
        f"/api/v1/series/{sid}/movement",
        f"/api/v1/series/{sid}/seasonality",
        f"/api/v1/series/{sid}/brief",
        f"{G}/series/{sid}",
        f"{G}/series/{sid}/observations",
        f"/api/v1/series/{sid}/environment",
    ]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda u: client.get(u).status_code, urls))
    assert set(codes) == {200}
    # catalog row, country's last period, the series' records, peer ids and the peer panel: once each, the rest are hits
    assert len(calls) <= 5, calls
    again = len(calls)
    for u in urls:
        assert client.get(u).status_code == 200
    assert len(calls) == again, "a repeat page load must not query DuckDB at all for this series"


def test_a_caller_cannot_corrupt_the_cache(world):
    _, _, sid = world
    gp = _gp()
    row = gp.series_row_raw(sid)
    row["commodity_name"] = "TAMPERED"
    assert gp.series_row_raw(sid)["commodity_name"] != "TAMPERED"
    rows = gp.raw_rows("TST", sid)
    before = rows.copy()
    rows["price"] = -1.0
    rows["used"] = False
    pd.testing.assert_frame_equal(gp.raw_rows("TST", sid), before)


def test_the_peer_cache_has_a_byte_budget(world, monkeypatch):
    _, _, _ = world
    cache = prices._LRU(10, max_bytes=2_000, weigh=lambda df: int(df.memory_usage(deep=False).sum()))
    small = pd.DataFrame({"a": [1.0] * 40})  # about 320 bytes plus index
    for i in range(30):
        cache.put(("k", i), small)
    assert cache.nbytes <= 2_000 and len(cache) < 10  # the byte budget bites before the entry count
    big = pd.DataFrame({"a": [1.0] * 5_000})
    cache.put(("big",), big)
    assert cache.get(("big",)) == (False, None)  # larger than the whole budget: never retained
    assert cache.nbytes <= 2_000


def test_the_cache_is_bounded(world, monkeypatch):
    client, _, _ = world
    gp = _gp()
    monkeypatch.setattr(gp, "_series_cache", prices._LRU(2))
    for i in client.get(f"{G}/countries/TST/series?limit=50&usable_only=false").json()["items"]:
        gp.series_row_raw(i["series_id"])
    assert len(gp._series_cache) == 2


def test_oversized_series_are_not_cached(world, monkeypatch):
    _, _, sid = world
    gp = _gp()
    gp.invalidate()
    monkeypatch.setattr(prices, "SERIES_CACHE_MAX_ROWS", 3)
    first = gp.raw_rows("TST", sid)
    assert len(first) > 3
    assert not any(k[0] == "raw" for k in gp._series_cache._data)  # served, but not retained
    assert len(gp.raw_rows("TST", sid)) == len(first)


def test_a_new_snapshot_is_never_answered_from_the_old_entries(tmp_path: Path):
    data = tmp_path / "data"
    first = obs_rows(months=24)
    sid = first["series_id"].iloc[0]
    write_country(data, "TST", first)
    build_catalog_for(data)
    with deployment(data, tmp_path) as client:
        gp = _gp()
        assert client.get(f"/api/v1/series/{sid}").json()["summary"]["latest_price"] == 123.0
        assert len(gp.raw_rows("TST", sid)) == 24
        write_country(data, "TST", obs_rows(months=25, prices={23: 999.0}))
        build_catalog_for(data)
        gp.invalidate()  # the server notices a new snapshot on its next source scan
        assert client.get(f"/api/v1/series/{sid}").json()["summary"]["latest_price"] == 124.0
        assert len(gp.raw_rows("TST", sid)) == 25


def test_responses_say_where_the_time_went(world):
    client, _, sid = world
    r = client.get(f"/api/v1/series/{sid}")
    timing = r.headers["server-timing"]
    assert "queue;dur=" in timing and "app;dur=" in timing
    assert "server-timing" not in client.get("/health").headers  # liveness probes are not gated or timed


def test_threads_share_one_cache_without_error(world):
    """Hammer the same and different series from many threads: no exception, identical answers."""
    _, _, sid = world
    gp = _gp()
    gp.invalidate()
    out: list[str] = []
    errors: list[BaseException] = []

    def work(_: int) -> None:
        try:
            out.append(json.dumps(gp.series_row(sid), sort_keys=True, default=str))
            gp.raw_rows("TST", sid)
        except BaseException as e:  # the test must report any failure from any thread
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(out)) == 1 and len(out) == 24
