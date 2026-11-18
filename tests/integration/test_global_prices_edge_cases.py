"""Edge cases of the global price layer on synthetic partitions (offline, deterministic).

Real-data journeys are in ``test_global_prices_real.py``; this file covers what real data happens not to
contain: invalid and conflicting records, missing and invalid coordinates, empty histories, snapshot
revisions, units and currencies that must never be mixed, and exported-data fidelity.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.global_support import build_catalog_for, deployment, obs_rows, write_country

G = "/api/v1/global"


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, Path, dict[str, str]]]:
    root = tmp_path_factory.mktemp("edge")
    data = root / "data"
    ids: dict[str, str] = {}
    parts = {
        "complete": obs_rows(),
        "other_market": obs_rows(market=("2", "Beta", 0.0, 0.0), base=120.0),  # 0,0 placeholder coordinates
        "no_coords": obs_rows(market=("3", "Gamma", None, None), base=90.0),
        "bad_coords": obs_rows(market=("4", "Delta", 95.0, 200.0), base=80.0),
        "gap": obs_rows(market=("5", "Epsilon", 11.0, 21.0), skip={5, 6, 7, 20}),
        "other_unit": obs_rows(unit="100 KG", base=10000.0),
        "other_currency": obs_rows(currency="USD", base=2.0, market=("6", "Zeta", 12.0, 22.0)),
        "wheat": obs_rows(commodity=("20", "Wheat"), base=150.0),
        "wholesale": obs_rows(price_type="Wholesale", base=95.0),
        "bad_records": obs_rows(
            market=("7", "Eta", 13.0, 23.0),
            commodity=("30", "Rice"),
            prices={4: -1.0},
            flags={4: "invalid_price"},
            extra=[(9, 777.0, "duplicate_conflict"), (12, 555.0, "")],  # a second record for month 12
        ),
        "all_invalid": obs_rows(
            market=("8", "Theta", 14.0, 24.0),
            commodity=("40", "Sorghum"),
            months=3,
            prices={0: -1.0, 1: -2.0, 2: 0.0},
            flags={0: "invalid_price", 1: "invalid_price", 2: "invalid_price"},
        ),
    }
    frame = pd.concat(parts.values(), ignore_index=True).sort_values(["series_id", "period", "price"], kind="stable")
    write_country(data, "TST", frame.reset_index(drop=True))
    write_country(data, "TSB", obs_rows(country="TSB", currency="TSH", base=100.0))
    build_catalog_for(data)
    for name, df in parts.items():
        ids[name] = df["series_id"].iloc[0]
    with deployment(data, root) as client:
        yield client, data, ids


def test_country_summary_and_tier(world):
    client, _, _ = world
    d = client.get(f"{G}/countries").json()
    assert {c["country_iso3"] for c in d["countries"]} == {"TST", "TSB"}
    tst = next(c for c in d["countries"] if c["country_iso3"] == "TST")
    assert tst["series"] == 11 and tst["markets"] == 8
    assert tst["status"] == "ingested" and not tst["research_eligible"]  # no registry: never claimed as research data
    assert d["totals"]["series"] == 12


def test_coordinates_are_classified_never_fabricated(world):
    client, _, _ = world
    items = {m["market_name"]: m for m in client.get(f"{G}/countries/TST/markets").json()["items"]}
    assert items["Alpha"]["coordinate_status"] == "ok" and items["Alpha"]["lat"] == 10.0
    assert items["Beta"]["coordinate_status"] == "invalid"  # 0,0
    assert items["Gamma"]["coordinate_status"] == "missing" and items["Gamma"]["lat"] is None
    assert items["Delta"]["coordinate_status"] == "invalid"  # out of range
    d = client.get(f"{G}/countries/TST/markets").json()
    assert d["markets_without_valid_coordinates"] == 3


def test_series_with_no_valid_prices_is_listed_not_hidden(world):
    client, _, ids = world
    rows = client.get(f"{G}/countries/TST/series?usable_only=false&commodity=40").json()["items"]
    assert len(rows) == 1 and rows[0]["series_id"] == ids["all_invalid"]
    assert rows[0]["n_observations"] == 0 and rows[0]["usable"] is False and rows[0]["first_period"] is None
    assert "no valid" in rows[0]["ineligible_reasons"]
    assert client.get(f"{G}/countries/TST/series?commodity=40").json()["total"] == 0  # default view: usable only
    detail = client.get(f"{G}/series/{ids['all_invalid']}").json()
    assert detail["summary"]["status"] == "no_valid_prices"
    assert detail["completeness"]["records_stored"] == 3 and detail["completeness"]["records_not_valid"] == 3
    obs = client.get(f"{G}/series/{ids['all_invalid']}/observations").json()
    assert obs["total"] == 3 and not any(o["valid"] for o in obs["items"])
    assert client.get(f"/api/v1/series/{ids['all_invalid']}/history").json()["n_observed"] == 0


def test_observation_flags_duplicates_and_what_feeds_the_series(world):
    client, _, ids = world
    sid = ids["bad_records"]
    d = client.get(f"{G}/series/{sid}").json()
    c = d["completeness"]
    assert c["records_stored"] == 32 and c["records_not_valid"] == 2
    assert c["quality_flag_counts"] == {"invalid_price": 1, "duplicate_conflict": 1}
    obs = client.get(f"{G}/series/{sid}/observations?limit=1000").json()["items"]
    by = {}
    for o in obs:
        by.setdefault(o["period"], []).append(o)
    assert [o["valid"] for o in by["2023-05-01"]] == [False]  # the invalid_price record
    dup = by["2023-10-01"]
    assert [o["valid"] for o in dup] == [True, False] or [o["valid"] for o in dup] == [False, True]
    assert all(o["duplicate_month"] for o in dup) and sum(o["used_in_series"] for o in dup) == 1
    assert next(o for o in dup if o["used_in_series"])["price"] == 109.0  # the valid one, never the conflicting 777
    twin = by["2024-01-01"]
    assert len(twin) == 2 and sum(o["used_in_series"] for o in twin) == 1  # two valid records: the first is used
    hist = client.get(f"/api/v1/series/{sid}/history").json()
    assert hist["excluded_records"] == 3  # invalid, conflicting and the later duplicate


def test_missing_months_are_explicit_never_interpolated(world):
    client, _, ids = world
    sid = ids["gap"]
    d = client.get(f"{G}/series/{sid}").json()["completeness"]
    assert d["months_spanned"] == 30 and d["valid_months"] == 26 and d["missing_months"] == 4
    assert d["longest_gap_months"] == 3
    hist = client.get(f"/api/v1/series/{sid}/history").json()
    nulls = [p["period"] for p in hist["items"] if p["price"] is None]
    assert nulls == ["2023-06-01", "2023-07-01", "2023-08-01", "2024-09-01"]
    assert hist["n_missing"] == 4


def test_series_identity_separates_units_currencies_and_price_types(world):
    client, _, ids = world
    distinct = {ids[k] for k in ("complete", "other_unit", "other_currency", "wholesale")}
    assert len(distinct) == 4
    rows = client.get(f"{G}/countries/TST/series?commodity=10&usable_only=false&limit=500").json()["items"]
    keys = {(r["market_code"], r["unit"], r["currency"], r["price_type"]) for r in rows}
    assert len(keys) == len(rows)  # no two series share an identity
    com = {c["commodity_code"]: c for c in client.get(f"{G}/countries/TST/commodities").json()["items"]}
    assert com["10"]["units"] == ["100 KG", "KG"] and com["10"]["currencies"] == ["TSH", "USD"]
    assert com["10"]["price_types"] == ["Retail", "Wholesale"]


def test_compare_never_mixes_incompatible_levels(world):
    client, _, ids = world

    def cmp(a: str, b: str) -> dict:
        return client.get(f"/api/v1/compare?series_id={ids[a]}&series_id={ids[b]}").json()

    ok = cmp("complete", "other_market")
    assert ok["status"] == "ok" and ok["comparability"]["level"] == "absolute_and_indexed"
    cur = cmp("complete", "other_currency")  # same thing, different currency: indexed only, no conversion
    assert cur["comparability"]["level"] == "indexed_only" and "no conversion" in " ".join(
        cur["comparability"]["reasons"]
    )
    for other in ("other_unit", "wheat", "wholesale"):
        r = cmp("complete", other)
        assert r["status"] == "not_comparable" and r["rows"] == [], other
    csv_refused = client.get(f"/api/v1/compare?series_id={ids['complete']}&series_id={ids['other_unit']}&format=csv")
    assert csv_refused.status_code == 409


def test_pagination_and_date_filtering(world):
    client, _, ids = world
    sid = ids["complete"]
    pages = []
    for off in range(0, 30, 7):
        p = client.get(f"{G}/series/{sid}/observations?limit=7&offset={off}").json()
        assert p["total"] == 30 and p["limit"] == 7
        pages += p["items"]
    assert [o["period"] for o in pages] == [str(d.date()) for d in pd.date_range("2023-01-01", periods=30, freq="MS")]
    w = client.get(f"{G}/series/{sid}/observations?start=2023-06&end=2023-08").json()
    assert [o["period"] for o in w["items"]] == ["2023-06-01", "2023-07-01", "2023-08-01"] and w["total"] == 3
    assert client.get(f"{G}/series/{sid}/observations?start=2024-01&end=2023-01").status_code == 422
    assert client.get(f"{G}/series/{sid}/observations?start=2023-13").status_code == 422
    assert client.get(f"{G}/series/{sid}/observations?limit=1001").status_code == 422
    assert client.get(f"{G}/series/{sid}/observations?offset=500").json()["items"] == []
    s = client.get(f"{G}/countries/TST/series?usable_only=false&limit=3&offset=3").json()
    assert s["total"] == 11 and len(s["items"]) == 3 and s["offset"] == 3


def test_search_and_filters_are_parameterised(world):
    client, _, _ = world
    q = client.get(f"{G}/countries/TST/series?q=wheat").json()
    assert q["total"] == 1 and q["items"][0]["commodity_name"] == "Wheat"
    inj = client.get(f"{G}/countries/TST/series", params={"q": "x'; DROP TABLE a;--"}).json()
    assert inj["total"] == 0
    assert (
        client.get(f"{G}/countries/TST/series", params={"q": "%%"}).json()["total"] == 0
    )  # LIKE wildcards are literal
    assert client.get(f"{G}/countries/TST/series?currency=USD").json()["total"] == 1
    assert client.get(f"{G}/countries/TST/series?price_type=wholesale").json()["total"] == 1
    assert (
        client.get(f"{G}/countries/TST/series?commodity=99999").json()["total"] == 0
    )  # unknown commodity: empty, not 500
    assert client.get(f"{G}/countries/TST/series?sort=bogus").status_code == 422


def test_identifier_validation(world):
    client, _, ids = world
    assert client.get(f"{G}/countries/tst").status_code == 422
    assert client.get(f"{G}/countries/TS").status_code == 422
    assert client.get(f"{G}/countries/ZZZ").status_code == 404
    assert client.get(f"{G}/countries/ZZZ/series").status_code == 404
    assert client.get(f"{G}/countries/..%2F..%2Fetc/series").status_code in (404, 422)
    assert client.get(f"{G}/series/not-a-series").status_code == 422
    assert client.get(f"{G}/series/ps_0000000000000000").status_code == 404
    assert client.get(f"{G}/series/ps_0000000000000000/observations").status_code == 404
    assert client.get("/api/v1/series/ps_0000000000000000").status_code == 404
    assert client.get(f"{G}/series/{ids['complete']}/export?format=xml").status_code == 422


def test_export_matches_the_observations_endpoint_and_the_partition(world):
    client, data, ids = world
    sid = ids["bad_records"]
    api = client.get(f"{G}/series/{sid}/observations?limit=1000").json()["items"]
    js = client.get(f"{G}/series/{sid}/export?format=json").json()
    assert js["items"] == api and js["series"]["series_id"] == sid
    r = client.get(f"{G}/series/{sid}/export?format=csv")
    assert r.headers["content-disposition"].endswith(f'market_almanac_{sid}.csv"')
    body = [line for line in r.text.splitlines() if not line.startswith("# ")]
    assert any(line.startswith("# ") and sid in line for line in r.text.splitlines())
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))
    assert len(rows) == len(api)
    for c, o in zip(rows, api, strict=True):
        assert c["period"] == o["period"]
        assert (float(c["price"]) if c["price"] else None) == o["price"]  # repr(): lossless float round trip
        assert c["valid"] == str(o["valid"]).lower() and c["quality_flags"] == ";".join(o["quality_flags"])
        assert c["currency"] == "TSH" and c["unit"] == "KG" and c["price_type"] == "Retail"
    # and against the stored Parquet, read independently of the API
    from market_almanac.globaldata.partitions import PartitionStore

    store = PartitionStore(data / "lake" / "live", "live")
    snap = store.latest("prices", "TST")
    raw = pd.read_parquet(store.path("prices", "TST", snap.snapshot_id))
    raw = raw[raw["series_id"] == sid].sort_values("period", kind="stable")
    assert sorted(o["price"] for o in api) == sorted(raw["price"].tolist())
    windowed = client.get(f"{G}/series/{sid}/export?format=json&start=2023-03&end=2023-04").json()["items"]
    assert [o["period"] for o in windowed] == ["2023-03-01", "2023-04-01"]


def test_summary_endpoint_reports_provenance_and_snapshot(world):
    client, _, ids = world
    d = client.get(f"{G}/series/{ids['complete']}").json()
    prov = d["provenance"]
    country = client.get(f"{G}/countries/TST").json()
    assert prov["snapshot_id"] == country["snapshot"]["snapshot_id"] == d["series"]["snapshot_id"]
    assert len(prov["file_sha256"]) == 64 and len(prov["observation_hash"]) == 64
    assert "WFP" in prov["attribution"] and "month the price describes" in prov["observation_basis"]
    assert d["country"]["forecast_evaluated"] is False and d["country"]["evaluation_records"] == []
    assert d["summary"]["latest_period"] == "2025-06-01" and d["summary"]["latest_price"] == 129.0


def test_series_pages_use_the_same_data_for_any_country(world):
    client, _, ids = world
    sid = ids["complete"]
    detail = client.get(f"/api/v1/series/{sid}").json()
    assert detail["series"]["country_iso3"] == "TST" and detail["provenance"]["snapshot_id"]
    mv = client.get(f"/api/v1/series/{sid}/movement")
    assert mv.status_code == 200
    assert client.get(f"/api/v1/series/{sid}/seasonality").status_code == 200
    env = client.get(f"/api/v1/series/{sid}/environment").json()
    assert env["status"] == "no_weather"  # no weather is claimed where none is stored
    brief = client.get(f"/api/v1/series/{sid}/brief").json()
    assert "Forecast" not in brief["text"] or brief["evidence"]["forecast"] is None


def test_revision_makes_the_catalog_stale_until_rebuilt(tmp_path: Path):
    data = tmp_path / "data"
    first = obs_rows(months=24)
    sid = first["series_id"].iloc[0]
    s1 = write_country(data, "TST", first)
    build_catalog_for(data)
    with deployment(data, tmp_path) as client:
        c = client.get(f"{G}/countries/TST").json()
        assert c["snapshot"]["snapshot_id"] == s1 and c["snapshot"]["revision"] == "initial"
        assert client.get(f"{G}/series/{sid}").json()["summary"]["latest_price"] == 123.0
        # WFP revises one price and adds a month: a new immutable snapshot, with the diff recorded
        revised = obs_rows(months=25, prices={23: 999.0})
        s2 = write_country(data, "TST", revised)
        assert s2 != s1
        from market_almanac_api.deps import global_prices

        global_prices().invalidate()
        stale = client.get(f"{G}/countries/TST")
        assert stale.status_code == 503 and "global catalog" in stale.json()["detail"]
        assert client.get(f"{G}/status").json()["stale_countries"] == ["TST"]
        build_catalog_for(data)
        global_prices().invalidate()
        c2 = client.get(f"{G}/countries/TST").json()
        assert c2["snapshot"]["snapshot_id"] == s2 and c2["snapshot"]["revision"] == "changed"
        assert c2["snapshot"]["parent_snapshot_id"] == s1
        assert c2["snapshot"]["diff"] == {"added": 1, "removed": 0, "revised": 1}
        d = client.get(f"{G}/series/{sid}").json()
        assert d["provenance"]["snapshot_id"] == s2 and d["summary"]["n_observations"] == 25
        assert d["summary"]["latest_price"] == 124.0
        # the old snapshot is untouched on disk, so work that cited it stays reproducible
        assert (data / "lake/live/partitions/prices/TST" / s1 / "data.parquet").exists()


def test_nothing_installed_is_a_clear_503_not_a_500(tmp_path: Path):
    with deployment(tmp_path / "data", tmp_path) as client:
        r = client.get(f"{G}/countries")
        assert r.status_code == 503 and "No price data" in r.json()["detail"]
        s = client.get(f"{G}/status").json()
        assert s["ready"] is False and s["countries"] == 0
        assert client.get("/health").status_code == 200


def test_catalog_missing_for_installed_partitions_is_reported(tmp_path: Path):
    data = tmp_path / "data"
    write_country(data, "TST", obs_rows())
    with deployment(data, tmp_path) as client:
        r = client.get(f"{G}/countries")
        assert r.status_code == 503 and "market-almanac global catalog" in r.json()["detail"]


def test_single_snapshot_lake_without_a_catalog_is_served_through_the_same_endpoints(tmp_path: Path):
    """Demo mode and development checkouts keep one price snapshot for all countries and no materialised catalog."""
    from market_almanac.data.store import DatasetStore

    data = tmp_path / "data"
    frame = obs_rows(country="TST")
    DatasetStore(data / "lake" / "live", "live").write("prices", frame, providers=["hdx_hapi"], merge_with_latest=False)
    with deployment(data, tmp_path) as client:
        d = client.get(f"{G}/countries").json()
        assert d["layout"] == "single_snapshot" and [c["country_iso3"] for c in d["countries"]] == ["TST"]
        sid = client.get(f"{G}/countries/TST/series").json()["items"][0]["series_id"]
        assert client.get(f"{G}/series/{sid}/observations").json()["total"] == 30
        assert client.get(f"/api/v1/series/{sid}/history").json()["n_observed"] == 30
        # the catalog was built into the cache directory, never into the data directory
        assert not (data / "public" / "live" / "series_catalog.parquet").exists()


def test_concurrent_requests_never_run_more_than_the_allowed_queries_at_once(world, monkeypatch):
    """A burst of visitors must not multiply DuckDB memory budgets: queries are gated to MAX_CONCURRENT_QUERIES."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from market_almanac.globaldata import prices

    client, _, ids = world
    state = {"now": 0, "peak": 0}
    guard = threading.Lock()
    real = prices._connect

    def slow_connect():
        with guard:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.02)  # hold the slot long enough for other threads to pile up behind it
        return real()

    class Tracked:
        def __init__(self, con):
            self._c = con

        def execute(self, *a, **k):
            return self._c.execute(*a, **k)

        def close(self):
            self._c.close()
            with guard:
                state["now"] -= 1

    monkeypatch.setattr(prices, "_connect", lambda: Tracked(slow_connect()))
    urls = [f"{G}/countries/TST/series", f"{G}/series/{ids['complete']}/observations", f"{G}/countries/TST/markets"] * 8
    with ThreadPoolExecutor(max_workers=16) as pool:
        codes = list(pool.map(lambda u: client.get(u).status_code, urls))
    assert set(codes) == {200}
    assert state["peak"] <= prices.MAX_CONCURRENT_QUERIES, state
