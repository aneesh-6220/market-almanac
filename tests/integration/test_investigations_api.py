"""Price Shock Investigator API on the seeded synthetic demo (offline): discovery, investigations, exports, limits."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from market_almanac.analytics.evidence import ztext


@pytest.fixture(scope="module")
def client(seeded_env):  # type: ignore[no-untyped-def]
    from market_almanac_api.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def shock_page(client):  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/shocks", params={"kind": "all", "direction": "any", "limit": 100})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def unusual(client):  # type: ignore[no-untyped-def]
    page = client.get("/api/v1/shocks", params={"limit": 100}).json()
    assert page["items"], "the demo data should contain at least one unusual rise"
    return page["items"][0]


def test_discovery_is_bounded_filtered_and_documented(client, shock_page):
    assert shock_page["total"] >= len(shock_page["items"]) > 0
    assert shock_page["method_version"] == "shock-1" and shock_page["definitions"]["caution"]
    it = shock_page["items"][0]
    for k in ("series_id", "country_iso3", "market_name", "commodity_name", "unit", "currency", "kind", "peak"):
        assert it[k] is not None, k
    assert {i["kind"] for i in shock_page["items"]} <= {"unusual", "large_typical", "withheld"}
    country = it["country_iso3"]
    only = client.get("/api/v1/shocks", params={"country": country, "kind": "all", "direction": "any"}).json()
    assert {i["country_iso3"] for i in only["items"]} == {country}
    down = client.get("/api/v1/shocks", params={"direction": "down", "kind": "all", "limit": 100}).json()
    assert all(i["direction"] == "down" for i in down["items"])
    wide = client.get("/api/v1/shocks", params={"kind": "all", "direction": "any", "include_non_food": True}).json()
    assert wide["total"] >= shock_page["total"]  # non-food items are excluded by default, never added
    paged = client.get("/api/v1/shocks", params={"kind": "all", "direction": "any", "limit": 2, "offset": 1}).json()
    assert paged["limit"] == 2 and paged["offset"] == 1 and len(paged["items"]) <= 2
    for bad in (
        {"limit": 101},
        {"limit": 0},
        {"offset": 10_001},
        {"country": "xx"},
        {"peak_from": "2020-1"},
        {"sort": "price"},
        {"kind": "crisis"},
        {"min_coverage": 1.5},
    ):
        assert client.get("/api/v1/shocks", params=bad).status_code == 422, bad


def test_discovery_withheld_and_large_typical_are_kept_apart(client):
    for kind in ("unusual", "large_typical", "withheld"):
        page = client.get("/api/v1/shocks", params={"kind": kind, "direction": "any", "limit": 50}).json()
        assert all(i["kind"] == kind for i in page["items"])
        if kind == "withheld":
            assert all(i["withheld_reason"] and i["peak_z"] is None for i in page["items"])
        if kind == "unusual":
            assert all(abs(i["peak_z"]) >= 2 for i in page["items"])


def test_facets(client, unusual):
    f = client.get("/api/v1/shocks/facets", params={"country": unusual["country_iso3"]}).json()
    assert f["commodities"] and all(c["n"] > 0 for c in f["commodities"])
    assert client.get("/api/v1/shocks/facets", params={"country": "x"}).status_code == 422


def test_investigation_document(client, unusual):
    r = client.get(f"/api/v1/investigations/{unusual['series_id']}")
    assert r.status_code == 200, r.text
    d = r.json()
    s = d["subject"]
    assert s["series_id"] == unusual["series_id"] and s["currency"] and s["unit"]
    assert d["config"]["format"] == "investigation-1" and len(d["config_id"]) == 16
    assert d["question"].startswith("Was the ")
    for section in ("observed_facts", "quantitative", "mechanisms", "gaps", "unsupported", "conclusion", "assessment"):
        assert d["evidence"][section], section
    assert {m["status"] for m in d["evidence"]["mechanisms"]} <= {
        "consistent",
        "partly_consistent",
        "less_likely",
        "not_indicated",
        "context_only",
        "cannot_be_assessed",
    }
    assert all(x["inference"] != "causal" for x in d["evidence"]["observed_facts"] + d["evidence"]["quantitative"])
    assert all(x["inference"] in ("causal", "predictive", "descriptive") for x in d["evidence"]["unsupported"])
    # comparisons preserve commodity, unit, price type and currency semantics
    for p in d["peers"]["rows"]:
        assert (p["commodity_name"], p["unit"], p["price_type"]) == (s["commodity_name"], s["unit"], s["price_type"])
    for m in d["breadth"]["rows"]:
        assert m["commodity_name"] != s["commodity_name"]
    assert len(d["peers"]["rows"]) <= 60 and len(d["breadth"]["rows"]) <= 40
    # missing context is reported as missing, never as zero
    mac = d["context"]["macro"]
    if not mac["cpi"]:
        assert mac["real_yoy_pct"] is None
    assert d["signals"] and all(x["price"] is None or x["price"] > 0 for x in d["signals"])
    missing = [x for x in d["signals"] if x["price"] is None]
    assert all(x["yoy_pct"] is None and x["z"] is None for x in missing)


def test_permalink_reproduces_the_same_document(client, unusual):
    sid = unusual["series_id"]
    d1 = client.get(f"/api/v1/investigations/{sid}").json()
    cfg = d1["config"]
    q = {"event": cfg["event"], "start": cfg["window"]["start"], "end": cfg["window"]["end"]}
    d2 = client.get(f"/api/v1/investigations/{sid}", params=q).json()
    assert d2["config"] == cfg and d2["config_id"] == d1["config_id"]
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)
    # a different month is a different configuration
    months = [x["period"] for x in d1["signals"] if x["price"] is not None]
    other = next(m for m in months if m != cfg["event"])
    d3 = client.get(f"/api/v1/investigations/{sid}", params={"event": other}).json()
    assert d3["config"]["event"] == other and d3["config_id"] != d1["config_id"]


def test_exports_match_the_document(client, unusual):
    sid = unusual["series_id"]
    d = client.get(f"/api/v1/investigations/{sid}").json()
    md = client.get(f"/api/v1/investigations/{sid}/export", params={"format": "md"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in md.headers["content-disposition"]
    text = md.text
    assert d["config_id"] in text and d["config"]["snapshot_id"] in text and d["question"] in text
    assert d["evidence"]["conclusion"]["text"] in text
    un = d["unusualness"]
    if un["status"] == "ok":
        assert f"robust z-score {ztext(un['z'])}" in text and f"{un['n_reference']} earlier 12-month changes" in text
    yoy = d["magnitude"]["event_yoy_pct"]
    if yoy is not None:
        assert f"{yoy * 100:+.1f}%" in text
    for m in d["evidence"]["mechanisms"]:
        assert m["name"] in text
    if not d["context"]["macro"]["cpi"]:
        assert "Consumer price index: not integrated" in text
    js = client.get(f"/api/v1/investigations/{sid}/export", params={"format": "json"})
    assert json.loads(js.text) == d
    rows = list(
        csv.DictReader(
            io.StringIO(
                client.get(f"/api/v1/investigations/{sid}/export", params={"format": "csv", "table": "signals"}).text
            )
        )
    )
    assert len(rows) == len(d["signals"]) and rows[0]["period"] == d["signals"][0]["period"]
    peers = list(
        csv.DictReader(
            io.StringIO(
                client.get(f"/api/v1/investigations/{sid}/export", params={"format": "csv", "table": "peers"}).text
            )
        )
    )
    assert len(peers) == len(d["peers"]["rows"])
    link = client.get(f"/api/v1/investigations/{sid}/export", params={"format": "md", "link": "https://example.org"})
    assert f"https://example.org/investigate?series={sid}&event={d['config']['event']}" in link.text
    assert client.get(f"/api/v1/investigations/{sid}/export", params={"link": "javascript:alert(1)"}).status_code == 422


def test_invalid_configurations_are_refused(client, unusual):
    sid = unusual["series_id"]
    assert client.get("/api/v1/investigations/ps_0000000000000000").status_code == 404
    assert client.get("/api/v1/investigations/not-an-id").status_code == 422
    assert client.get(f"/api/v1/investigations/{sid}", params={"event": "2020-13"}).status_code == 422
    r = client.get(f"/api/v1/investigations/{sid}", params={"event": "1990-01"})
    assert r.status_code == 422 and "within the series" in r.json()["detail"]
    d = client.get(f"/api/v1/investigations/{sid}").json()
    r = client.get(
        f"/api/v1/investigations/{sid}",
        params={"event": d["config"]["event"], "start": d["config"]["event"], "end": d["config"]["event"]},
    )
    assert r.status_code == 200 and r.json()["config"]["window"]["start"] == d["config"]["event"]
    after = client.get(
        f"/api/v1/investigations/{sid}", params={"event": d["config"]["window"]["start"], "start": d["config"]["event"]}
    )
    assert after.status_code == 422


def test_discovery_row_and_investigation_agree(client, unusual):
    d = client.get(f"/api/v1/investigations/{unusual['series_id']}", params={"event": unusual["peak"]}).json()
    ep = d["episode"]
    assert ep and ep["kind"] == "unusual"
    assert ep["start"][:7] == unusual["start"] and ep["end"][:7] == unusual["end"]
    assert ep["peak_z"] == pytest.approx(unusual["peak_z"], rel=1e-5)
    assert ep["peak_yoy_pct"] == pytest.approx(unusual["peak_yoy_pct"], rel=1e-5)
    if unusual["extent"]:
        n_all = unusual["peer_n"]
        if n_all <= 60:
            assert d["peers"]["extent"]["class"] == unusual["extent"]
