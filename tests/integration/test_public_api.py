"""Public market-intelligence API against a seeded demo deployment."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(seeded_env):  # type: ignore[no-untyped-def]
    from shocktrace_api.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def series(client):  # type: ignore[no-untyped-def]
    page = client.get("/api/v1/catalog/series?limit=500").json()
    assert page["total"] == len(page["items"]) > 5
    return page["items"]


def test_catalog_search_filters_and_pagination(client, series):
    s0 = series[0]
    assert s0["first_period"] <= s0["last_period"] and s0["n_observations"] >= 12 and s0["currency"]
    code = s0["commodity_code"]
    only = client.get(f"/api/v1/catalog/series?commodity={code}&limit=500").json()
    assert only["items"] and {x["commodity_code"] for x in only["items"]} == {code}
    q = client.get(f"/api/v1/catalog/series?q={s0['market_name'][:4].lower()}").json()
    assert any(x["series_id"] == s0["series_id"] for x in q["items"])
    page = client.get("/api/v1/catalog/series?limit=2&offset=1").json()
    assert len(page["items"]) == 2 and page["offset"] == 1 and page["total"] == len(series)
    assert page["items"][0]["series_id"] == series[1]["series_id"] and page["snapshot_id"] and page["synthetic"] is True
    assert client.get("/api/v1/catalog/series?q=zzzzzz").json() == {**q, "items": [], "total": 0}
    for bad in ("limit=0", "limit=5000", "country=xx", "sort=price", "q=a"):
        assert client.get(f"/api/v1/catalog/series?{bad}").status_code == 422


def test_catalog_selectors_and_coverage(client, series):
    com = client.get("/api/v1/catalog/commodities").json()
    assert {c["commodity_code"] for c in com} == {s["commodity_code"] for s in series}
    assert all(c["usable_series"] <= c["series"] and c["units"] for c in com)
    mk = client.get(f"/api/v1/catalog/markets?commodity={com[0]['commodity_code']}").json()
    assert mk and all(x["series"] >= 1 for x in mk) and sum(x["lat"] is not None for x in mk) >= len(mk) - 1
    assert any(x["lat"] is None for x in client.get("/api/v1/catalog/markets").json())  # a market without coordinates
    cov = client.get("/api/v1/catalog/coverage").json()
    c = cov["countries"][0]
    assert c["country_iso3"] == "XDM" and c["series"] >= c["usable_series"] >= c["eligible_series"]
    assert c["features"]["price_history"] and c["features"]["forecast_evaluation"]
    assert c["forecast_evaluated_series"] <= c["series"]  # forecast coverage is the narrower set
    assert "not global coverage" in cov["scope_note"] and "forecast_evaluated" in cov["definitions"]
    assert cov["totals"]["series"] == sum(x["series"] for x in cov["countries"])


def test_series_detail_reports_observation_month_and_provenance(client, series):
    sid = series[0]["series_id"]
    d = client.get(f"/api/v1/series/{sid}").json()
    assert d["series"]["series_id"] == sid and d["summary"]["latest_period"] == d["series"]["last_period"]
    assert d["summary"]["latest_price"] > 0 and d["summary"]["changes"]["m1"]["reference_period"]
    prov = d["provenance"]
    assert prov["snapshot_id"] and "not the date it was" in prov["observation_basis"] and prov["attribution"]
    assert client.get("/api/v1/series/ps_0000000000000000").status_code == 404
    assert client.get("/api/v1/series/not-an-id").status_code == 422


def test_history_json_and_csv_keep_missing_months_explicit(client, series):
    sid = series[0]["series_id"]
    h = client.get(f"/api/v1/series/{sid}/history").json()
    assert h["n_observed"] + h["n_missing"] == len(h["items"]) and h["items"][0]["period"].endswith("-01")
    first, last = h["items"][0]["period"][:7], h["items"][5]["period"][:7]
    win = client.get(f"/api/v1/series/{sid}/history?start={first}&end={last}").json()
    assert len(win["items"]) == 6
    assert client.get(f"/api/v1/series/{sid}/history?start=2020-05&end=2019-01").status_code == 422
    r = client.get(f"/api/v1/series/{sid}/history?format=csv")
    assert r.headers["content-type"].startswith("text/csv") and sid in r.headers["content-disposition"]
    body = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))
    assert len(rows) == len(h["items"]) and set(rows[0]) == {"period", "price", "currency", "unit"}
    assert r.text.startswith("# ShockTrace series") and "not interpolated" in r.text


def test_movement_seasonality_environment(client, series):
    sid = next(s["series_id"] for s in series if s["eligible"])
    mv = client.get(f"/api/v1/series/{sid}/movement").json()
    a = mv["assessment"]
    assert a["status"] == "ok" and a["label"] in {"typical", "larger_than_usual", "unusual", "exceptional"}
    assert 0 <= a["overall"]["percentile_of_size"] <= 1 and a["overall"]["n_reference"] >= 24
    assert "not findings of a shortage" in mv["disclaimer"] and "method" in a
    assert mv["peers"] is None or mv["peers"]["status"] in {"ok", "too_few_peers"}
    past = client.get(f"/api/v1/series/{sid}/movement?at=2019-06").json()["assessment"]
    assert past["period"] == "2019-06-01"
    sea = client.get(f"/api/v1/series/{sid}/seasonality").json()
    assert sea["status"] == "ok" and len(sea["months"]) == 12 and 1 <= sea["peak_month"] <= 12
    env = client.get(f"/api/v1/series/{sid}/environment").json()
    assert env["status"] == "ok" and env["market_cell"]["location_id"].startswith("wx_")
    assert len(env["market_cell_series"]) == 60 and any(
        "correlation, not a demonstrated cause" in c for c in env["caveats"]
    )
    assert env["production_region"] is None  # the synthetic country has no crop-production weights


def test_brief_is_built_from_evidence(client, series):
    sid = next(s["series_id"] for s in series if s["eligible"])
    b = client.get(f"/api/v1/series/{sid}/brief").json()
    sections = {s["section"] for s in b["sentences"]}
    assert {"latest", "what_changed", "unusualness", "data", "environment", "forecast", "uncertainty"} <= sections
    assert b["text"] == " ".join(s["text"] for s in b["sentences"]) and b["synthetic"] is True
    ev = b["evidence"]
    assert ev["summary"]["latest_period"] == b["as_of_period"] and ev["forecast"]["experiment_id"].startswith("demo_")
    assert f"{ev['summary']['latest_price']:,.0f}" in b["text"] or f"{ev['summary']['latest_price']:,.2f}" in b["text"]
    assert "language model" in b["method"]


def test_compare_valid_invalid_and_csv(client, series):
    by_com: dict[str, list[dict]] = {}
    for s in series:
        by_com.setdefault(s["commodity_code"], []).append(s)
    same = next(v for v in by_com.values() if len(v) >= 3)[:3]
    ids = "&".join(f"series_id={s['series_id']}" for s in same)
    ok = client.get(f"/api/v1/compare?{ids}").json()
    assert ok["status"] == "ok" and ok["comparability"]["level"] == "absolute_and_indexed"
    assert len(ok["series"]) == 3 and len(ok["pairs"]) == 3 and ok["index_base"]["mode"] == "common_base"
    base = ok["index_base"]["base_period"]
    row = next(r for r in ok["rows"] if r["period"] == base)
    assert all(abs(v - 100) < 1e-9 for v in row["index"].values())
    assert ok["latest_common_spread"]["max_over_min"] >= 1 and [m["series_id"] for m in ok["series_meta"]] == [
        s["series_id"] for s in same
    ]
    other = next(v for k, v in by_com.items() if k != same[0]["commodity_code"])[0]
    bad = client.get(f"/api/v1/compare?series_id={same[0]['series_id']}&series_id={other['series_id']}").json()
    assert bad["status"] == "not_comparable" and bad["rows"] == []
    assert any("commodity name differs" in r for r in bad["comparability"]["reasons"])
    r = client.get(f"/api/v1/compare?{ids}&format=csv")
    assert r.status_code == 200 and "no currency conversion" in r.text and "index:" in r.text
    assert (
        client.get(
            f"/api/v1/compare?series_id={same[0]['series_id']}&series_id={other['series_id']}&format=csv"
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/compare?series_id={same[0]['series_id']}").status_code == 422
    assert (
        client.get(f"/api/v1/compare?series_id={same[0]['series_id']}&series_id={same[0]['series_id']}").status_code
        == 422
    )
    assert client.get("/api/v1/compare?series_id=abc&series_id=def").status_code == 422
    nine = "&".join(f"series_id=ps_{i:016x}" for i in range(9))
    assert client.get(f"/api/v1/compare?{nine}").status_code == 422  # resource limit


def test_movers_and_studies(client):
    mv = client.get("/api/v1/movers?limit=5").json()
    assert isinstance(mv, list) and all(x["series"]["movement_label"] in {"unusual", "exceptional"} for x in mv)
    assert client.get("/api/v1/movers?limit=1000").status_code == 422
    assert client.get("/api/v1/studies").json() == []
    assert client.get("/api/v1/studies/sahel-production-weather-v1").status_code == 404
    assert client.get("/api/v1/studies/..%2F..%2Fetc").status_code in (404, 422)


def test_openapi_documents_the_public_endpoints(client):
    spec = client.get("/openapi.json").json()
    for path in (
        "/api/v1/catalog/series",
        "/api/v1/catalog/coverage",
        "/api/v1/series/{series_id}",
        "/api/v1/series/{series_id}/history",
        "/api/v1/series/{series_id}/movement",
        "/api/v1/series/{series_id}/brief",
        "/api/v1/compare",
        "/api/v1/movers",
        "/api/v1/studies/{study_id}",
    ):
        assert path in spec["paths"] and list(spec["paths"][path]) == ["get"]
        assert spec["paths"][path]["get"].get("description") or spec["paths"][path]["get"].get("summary")
    assert all(set(v) <= {"get"} for v in spec["paths"].values())  # the public API is read-only


def test_peer_panel_matches_per_series_definition(client, series):  # type: ignore[no-untyped-def]
    """The vectorised, cached peer panel equals one column per comparable series built one by one."""
    import pandas as pd

    from shocktrace_api.deps import cache

    cat, _, _ = cache.catalog()
    sid = series[0]["series_id"]
    m = cat.loc[sid]
    same = cat[
        (cat["country_iso3"] == m["country_iso3"])
        & (cat["commodity_code"] == m["commodity_code"])
        & (cat["unit"] == m["unit"])
        & (cat["price_type"] == m["price_type"])
        & (cat["currency"] == m["currency"])
    ]
    expected = pd.DataFrame({s: cache.series_monthly(s) for s in same.index}).sort_index()
    panel = cache.peer_panel(cat, sid)
    pd.testing.assert_frame_equal(expected, panel, check_names=False, check_freq=False)
    assert cache.peer_panel(cat, sid) is panel  # cached per comparable group
