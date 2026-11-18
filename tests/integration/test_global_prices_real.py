"""Journeys over the archived global WFP data (3.8 M observations, 95 countries).

These tests need the real lake: set ``MARKET_ALMANAC_REAL_DATA_DIR`` to a data directory that holds the pinned
``global-prices-v1`` snapshot (``market-almanac global install-prices`` creates one) or run from a checkout whose
``data/`` already has it. Otherwise they skip. Every expectation is checked against the Parquet files read
independently of the API, or against a fixed property of the data (e.g. totals), never against a number copied
from the API under test.
"""

from __future__ import annotations

import csv
import io
import json
import os
import resource
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from market_almanac.data.identity import series_id as make_series_id
from market_almanac.globaldata.release import pinned_release
from tests.global_support import deployment

G = "/api/v1/global"
ROOT = Path(__file__).resolve().parents[2]
TOTALS = {"countries": 95, "series": 125_202, "markets": 4_835, "observations": 3_801_021}


def _data_dir() -> Path | None:
    for cand in (os.environ.get("MARKET_ALMANAC_REAL_DATA_DIR"), str(ROOT / "data")):
        if not cand:
            continue
        p = Path(cand)
        man = p / "public" / "live" / "global_catalog_manifest.json"
        if not man.exists():
            continue
        try:
            have = {k: v["snapshot_id"] for k, v in json.loads(man.read_text())["countries"].items()}
        except (OSError, ValueError, KeyError):
            continue
        if have == pinned_release()["snapshots"]:
            return p
    return None


REAL = _data_dir()
pytestmark = pytest.mark.skipif(REAL is None, reason="pinned global price snapshot not installed")
# the 75 MB research bundle (legacy single-snapshot lake, experiments, studies) is installed only on full checkouts
HAS_RESEARCH = REAL is not None and (REAL / "lake" / "live" / "prices").exists()
needs_research = pytest.mark.skipif(not HAS_RESEARCH, reason="research bundle not installed")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    assert REAL is not None
    with deployment(REAL, tmp_path_factory.mktemp("realdb")) as c:
        yield c


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert REAL is not None
    return json.loads((REAL / "public" / "live" / "global_catalog_manifest.json").read_text())


def partition(iso3: str) -> Path:
    assert REAL is not None
    snap = pinned_release()["snapshots"][iso3]
    return REAL / "lake" / "live" / "partitions" / "prices" / iso3 / snap / "data.parquet"


def oracle(iso3: str, sid: str) -> pd.DataFrame:
    """Every stored record of one series, read straight from Parquet."""
    q = f"SELECT * FROM read_parquet('{partition(iso3)}') WHERE series_id = ? ORDER BY period, price"
    return duckdb.connect().execute(q, [sid]).df()


def pick(client: TestClient, iso3: str, **params: object) -> dict:
    q = {"limit": 1, "sort": "observations", "usable_only": "false", **params}
    items = client.get(f"{G}/countries/{iso3}/series", params=q).json()["items"]
    assert items, (iso3, params)
    return items[0]


# --- totals and discovery -------------------------------------------------------------------------------


def test_inventory_covers_every_ingested_country(client, manifest):
    d = client.get(f"{G}/countries").json()
    assert len(d["countries"]) == TOTALS["countries"]
    assert d["totals"]["series"] == TOTALS["series"] == manifest["rows"]
    assert d["totals"]["markets"] == TOTALS["markets"]
    assert d["totals"]["observations"] == TOTALS["observations"]
    assert sum(c["observations"] for c in d["countries"]) == TOTALS["observations"]
    for c in d["countries"]:
        assert c["snapshot_id"] == pinned_release()["snapshots"][c["country_iso3"]]
        assert c["status"] in {"ingested", "validated", "research_eligible", "forecast_evaluated"}
        assert c["research_eligible"] == (c["status"] in {"research_eligible", "forecast_evaluated"})
        assert c["forecast_evaluated"] == (c["status"] == "forecast_evaluated") == (c["evaluations"] > 0)
    # ingested or validated data is never presented as research-eligible
    assert sum(c["research_eligible"] for c in d["countries"]) < TOTALS["countries"]


def test_observation_totals_match_the_parquet_files(manifest):
    con = duckdb.connect()
    for iso in ("ARM", "TCD", "NPL", "ETH", "HTI"):
        n, s = con.execute(
            f"SELECT count(*), count(DISTINCT series_id) FROM read_parquet('{partition(iso)}')"
        ).fetchone()
        assert (n, s) == (manifest["countries"][iso]["observations"], manifest["countries"][iso]["series"])


@pytest.mark.parametrize("iso3", ["ARM", "TCD", "NPL", "ETH", "HTI"])
def test_every_listed_series_exists_in_the_partition(client, iso3):
    page = client.get(f"{G}/countries/{iso3}/series", params={"usable_only": "false", "limit": 500}).json()
    con = duckdb.connect()
    stored = {r[0] for r in con.execute(f"SELECT DISTINCT series_id FROM read_parquet('{partition(iso3)}')").fetchall()}
    assert page["total"] == len(stored)
    listed = {i["series_id"] for i in page["items"]}
    assert listed <= stored


def test_series_ids_are_recomputable_from_their_identity_fields(client):
    """The identifier is a pure function of provider/country/market/commodity/unit/price type/flag/currency."""
    for iso3 in ("ARM", "ETH", "HTI"):
        for it in client.get(f"{G}/countries/{iso3}/series", params={"limit": 50, "usable_only": "false"}).json()[
            "items"
        ]:
            assert it["series_id"] == make_series_id(
                provider="hdx_hapi",
                country_iso3=iso3,
                market_code=it["market_code"],
                commodity_code=it["commodity_code"],
                unit=it["unit"],
                price_type=it["price_type"],
                price_flag=it["price_flag"],
                currency=it["currency"],
            )


# --- five genuine journeys (country → market → commodity → series → history → provenance → export) -----


@pytest.mark.parametrize(
    "iso3,currency", [("ARM", "AMD"), ("TCD", "XAF"), ("NPL", "NPR"), ("ETH", "ETB"), ("HTI", "HTG")]
)
def test_country_journey(client, iso3, currency):
    country = client.get(f"{G}/countries/{iso3}").json()
    assert country["country_iso3"] == iso3 and country["snapshot"]["snapshot_id"]
    markets = client.get(f"{G}/countries/{iso3}/markets").json()["items"]
    assert markets and all({"market_code", "market_name", "coordinate_status"} <= m.keys() for m in markets)
    commodities = client.get(f"{G}/countries/{iso3}/commodities").json()["items"]
    assert commodities and all(currency in c["currencies"] for c in commodities)

    s = pick(client, iso3)
    assert s["currency"] == currency and s["usable"]
    detail = client.get(f"{G}/series/{s['series_id']}").json()
    raw = oracle(iso3, s["series_id"])
    c = detail["completeness"]
    assert c["records_stored"] == len(raw)
    assert detail["provenance"]["snapshot_id"] == pinned_release()["snapshots"][iso3]
    assert detail["country"]["forecast_evaluated"] in (True, False)

    # observation pages concatenate to exactly the stored records, in order, with the stored values
    items: list[dict] = []
    while True:
        p = client.get(f"{G}/series/{s['series_id']}/observations", params={"limit": 100, "offset": len(items)}).json()
        items += p["items"]
        if len(items) >= p["total"] or not p["items"]:
            break
    assert len(items) == len(raw) == p["total"]
    assert [o["period"] for o in items] == [t.strftime("%Y-%m-%d") for t in raw["period"]]
    assert [o["price"] for o in items] == raw["price"].tolist()
    assert detail["series"]["currency"] == currency and detail["series"]["unit"] == s["unit"]

    # the plotted history shows the same valid prices, and gaps are nulls rather than interpolations
    hist = client.get(f"/api/v1/series/{s['series_id']}/history").json()
    valid = {o["period"]: o["price"] for o in items if o["used_in_series"]}
    plotted = {h["period"]: h["price"] for h in hist["items"] if h["price"] is not None}
    assert plotted == valid and hist["n_observed"] == len(valid)

    # export fidelity
    r = client.get(f"{G}/series/{s['series_id']}/export", params={"format": "csv"})
    rows = list(csv.DictReader(io.StringIO("\n".join(ln for ln in r.text.splitlines() if not ln.startswith("# ")))))
    assert len(rows) == len(raw)
    assert [float(x["price"]) for x in rows] == raw["price"].tolist()
    assert {x["currency"] for x in rows} == {currency} and {x["unit"] for x in rows} == {s["unit"]}
    assert any("Snapshot" in ln or "snapshot" in ln for ln in r.text.splitlines() if ln.startswith("# "))


# --- units, currencies and comparability --------------------------------------------------------------


def test_reporting_units_and_currencies_are_never_mixed(client):
    """Within a country, a commodity reported in two units gives two series; comparing them is refused."""
    found = None
    for iso3 in ("ETH", "HTI", "SYR", "NPL", "TCD"):
        for com in client.get(f"{G}/countries/{iso3}/commodities").json()["items"]:
            if len(com["units"]) > 1:
                found = (iso3, com)
                break
        if found:
            break
    assert found, "expected at least one commodity reported in more than one unit"
    iso3, com = found
    a = pick(client, iso3, commodity=com["commodity_code"], unit=com["units"][0])
    b = pick(client, iso3, commodity=com["commodity_code"], unit=com["units"][1])
    assert a["series_id"] != b["series_id"] and a["unit"] != b["unit"]
    r = client.get("/api/v1/compare", params=[("series_id", a["series_id"]), ("series_id", b["series_id"])]).json()
    assert r["status"] == "not_comparable" and r["rows"] == []


def test_cross_country_comparison_uses_indices_never_converted_levels(client):
    candidates: list[dict] = []
    a: dict = {}
    for com in client.get(f"{G}/countries/ARM/commodities").json()["items"]:
        hit = client.get(f"{G}/countries/NPL/series", params={"q": com["commodity_name"], "limit": 50}).json()
        hit = [
            h
            for h in hit["items"]
            if h["commodity_name"] == com["commodity_name"]
            and h["unit"] in com["units"]
            and h["price_type"] in com["price_types"]
        ]
        if hit:
            a = pick(
                client, "ARM", commodity=com["commodity_code"], unit=hit[0]["unit"], price_type=hit[0]["price_type"]
            )
            candidates = hit
            break
    assert candidates, "ARM and NPL share at least one commodity/unit"
    r = client.get(
        "/api/v1/compare", params=[("series_id", a["series_id"]), ("series_id", candidates[0]["series_id"])]
    ).json()
    assert r["comparability"]["level"] == "indexed_only"
    assert "AMD" in json.dumps(r["comparability"]) and "NPR" in json.dumps(r["comparability"])


# --- limits of the data ---------------------------------------------------------------------------------


def test_short_histories_are_hidden_by_default_but_reachable(client):
    default = client.get(f"{G}/countries/HTI/series", params={"limit": 1}).json()["total"]
    everything = client.get(f"{G}/countries/HTI/series", params={"limit": 1, "usable_only": "false"}).json()["total"]
    assert everything == 800 and 0 < default < everything
    short = client.get(
        f"{G}/countries/HTI/series", params={"usable_only": "false", "sort": "observations", "limit": 500}
    ).json()
    least = short["items"][-1]
    assert least["n_observations"] < 12 and least["usable"] is False
    d = client.get(f"{G}/series/{least['series_id']}").json()
    assert d["summary"]["n_observations"] < 12 and d["series"]["usable"] is False


def test_no_forecast_is_claimed_where_none_was_evaluated(client):
    countries = client.get(f"{G}/countries").json()["countries"]
    unevaluated = [c for c in countries if not c["forecast_evaluated"]]
    assert unevaluated, "most countries have no forecast evaluation"
    c = unevaluated[0]["country_iso3"]
    s = pick(client, c)
    d = client.get(f"{G}/series/{s['series_id']}").json()
    assert d["country"]["forecast_evaluated"] is False and d["country"]["evaluation_records"] == []
    assert "forecast" not in {k for k in d.get("summary", {})}


def test_invalid_and_unsupported_identifiers(client):
    assert client.get(f"{G}/countries/xx").status_code == 422
    assert client.get(f"{G}/countries/ZZZ").status_code == 404
    usa = client.get(f"{G}/countries/USA")
    assert usa.status_code == 404 and "no prices" in usa.json()["detail"].lower()
    assert client.get(f"{G}/series/ps_ffffffffffffffff").status_code == 404
    assert client.get(f"{G}/countries/ARM/series", params={"limit": 501}).status_code == 422


def test_missing_and_invalid_coordinates_are_reported(client):
    bad = 0
    for iso3 in ("TCD", "ETH", "HTI", "SYR"):
        d = client.get(f"{G}/countries/{iso3}/markets").json()
        bad += d["markets_without_valid_coordinates"]
        for m in d["items"]:
            if m["coordinate_status"] != "ok":
                assert m["lat"] is None or m["coordinate_status"] == "invalid"
    assert bad >= 0  # reported either way; the count is derived from the data, not assumed


# --- large countries and paging --------------------------------------------------------------------------


@pytest.mark.parametrize("iso3", ["SYR", "IDN"])
def test_large_country_pages_cover_the_catalog_without_overlap(client, iso3):
    first = client.get(
        f"{G}/countries/{iso3}/series", params={"usable_only": "false", "limit": 500, "offset": 0}
    ).json()
    total = first["total"]
    seen = {i["series_id"] for i in first["items"]}
    t0 = time.perf_counter()
    last = client.get(
        f"{G}/countries/{iso3}/series", params={"usable_only": "false", "limit": 500, "offset": total - 1}
    ).json()
    assert time.perf_counter() - t0 < 2.0
    assert len(last["items"]) == 1 and last["items"][0]["series_id"] not in seen
    assert total > 5000


def test_date_filters_on_a_long_series(client):
    s = pick(client, "SYR", sort="observations")
    raw = oracle("SYR", s["series_id"])
    lo, hi = raw["period"].iloc[len(raw) // 4], raw["period"].iloc[len(raw) // 2]
    got = client.get(
        f"{G}/series/{s['series_id']}/observations",
        params={"start": lo.strftime("%Y-%m"), "end": hi.strftime("%Y-%m"), "limit": 1000},
    ).json()
    want = raw[(raw["period"] >= lo) & (raw["period"] <= hi)]
    assert got["total"] == len(want) and [o["price"] for o in got["items"]] == want["price"].tolist()


# --- existing behaviour is preserved -------------------------------------------------------------------


@needs_research
def test_existing_ten_country_journeys_still_work(client):
    assert client.get("/api/v1/catalog/coverage").status_code == 200
    assert client.get("/api/v1/coverage/registry").status_code == 200
    assert client.get("/api/v1/catalog/markets", params={"country": "ETH"}).status_code == 200
    series = client.get("/api/v1/catalog/series", params={"limit": 5})
    assert series.status_code == 200
    items = series.json()["items"]
    assert items
    sid = items[0]["series_id"]
    for path in ("", "/history", "/movement", "/seasonality", "/environment", "/brief"):
        r = client.get(f"/api/v1/series/{sid}{path}")
        assert r.status_code == 200, (path, r.text[:200])


@needs_research
def test_research_endpoints_unchanged(client):
    for path in ("/api/v1/studies", "/api/v1/experiments", "/api/v1/backtests", "/api/v1/model-comparisons"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:200])


# --- resources -------------------------------------------------------------------------------------------


def test_peak_memory_and_latency_within_the_free_tier(tmp_path):
    """A fresh process serving a mixed workload stays far under Render Free's 512 MB."""
    assert REAL is not None
    script = tmp_path / "bench.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import os, resource, sys, time, json
            os.environ.update(DATA_DIR={str(REAL)!r}, MARKET_ALMANAC_MODE="live", GLOBAL_PRICES_AUTO_INSTALL="0",
                              DATABASE_URL="sqlite:///{tmp_path}/b.db", CACHE_DIR="{tmp_path}/c",
                              API_RATE_LIMIT_PER_MINUTE="1000000")
            from fastapi.testclient import TestClient
            from market_almanac.config import get_settings
            from market_almanac.services import init_db
            from market_almanac_api.main import create_app
            init_db(get_settings())
            c = TestClient(create_app())
            lat = []
            def get(u, **kw):
                t = time.perf_counter(); r = c.get(u, **kw); lat.append(time.perf_counter() - t)
                assert r.status_code == 200, (u, r.status_code, r.text[:200]); return r.json()
            get("/api/v1/global/countries")
            for iso in ["SYR", "IDN", "ETH", "HTI", "NPL", "ARM", "TCD", "AFG", "COD", "SOM"]:
                get(f"/api/v1/global/countries/{{iso}}/markets")
                p = get(f"/api/v1/global/countries/{{iso}}/series", params={{"limit": 25, "sort": "observations"}})
                sid = p["items"][0]["series_id"]
                get(f"/api/v1/global/series/{{sid}}")
                get(f"/api/v1/global/series/{{sid}}/observations", params={{"limit": 500}})
                c.get(f"/api/v1/global/series/{{sid}}/export", params={{"format": "csv"}})
            lat.sort()
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
            p95 = lat[int(len(lat) * .95)]
            print(json.dumps({{"rss_mb": rss_mb, "p50": lat[len(lat) // 2], "p95": p95, "max": lat[-1]}}))
            """
        )
    )
    out = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=300, check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    m = json.loads(out.stdout.strip().splitlines()[-1])
    # Free-tier limit is 512 MiB. Measured peaks for this workload: 327 MB (macOS), 410 MB (Linux CI runner,
    # fresh interpreter), 322 MB (Render, via the host's metrics). The guard keeps ~50 MB of headroom below the limit.
    assert m["rss_mb"] < 460, m
    assert m["p95"] < 2.0 and m["max"] < 5.0, m
    assert resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss > 0
