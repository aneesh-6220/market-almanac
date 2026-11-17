"""API integration tests against a fully seeded demo deployment (SQLite + Parquet)."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(seeded_env):  # type: ignore[no-untyped-def]
    from market_almanac_api.main import create_app

    return TestClient(create_app())


def test_health_and_status(client):
    assert client.get("/health").json()["status"] == "ok"
    s = client.get("/api/v1/status").json()
    assert s["mode"] == "demo" and s["synthetic"] is True
    assert any("SYNTHETIC" in n for n in s["notices"])
    assert {x["dataset"] for x in s["snapshots"]} >= {"prices", "weather_monthly", "macro"}
    assert all(x["synthetic"] for x in s["snapshots"])


def test_sources_never_claim_live_verification_without_live_success(client):
    src = client.get("/api/v1/sources").json()
    assert [x["provider_id"] for x in src] == ["hdx_hapi", "nasa_power", "world_bank", "imf", "faostat"]
    for x in src:
        assert x["verification"] == "fixture_tested_only"  # nothing was checked live in this test DB
        assert x["health_status"] == "unknown"
        assert x["attribution"] and x["license"]
    body = client.get("/api/v1/sources").text
    assert "app_identifier=" not in body and "Bearer" not in body


def test_discovery(client):
    assert client.get("/api/v1/countries").json()[0]["iso3"] == "XDM"
    markets = client.get("/api/v1/markets", params={"country": "XDM"}).json()
    assert len(markets) == 8
    nocoord = [m for m in markets if m["lat"] is None]
    assert len(nocoord) == 1 and nocoord[0]["weather_location_id"] is None
    assert client.get("/api/v1/commodities", params={"country": "XDM"}).status_code == 200
    ser = client.get("/api/v1/series", params={"country": "XDM"}).json()
    assert any(not s["eligible"] for s in ser) and any(s["eligible"] for s in ser)
    cov = client.get("/api/v1/coverage", params={"country": "XDM", "commodity": "DM-MAIZE"}).json()
    assert cov["months"] and all(len(r["observed"]) == len(cov["months"]) for r in cov["series"])


def test_data_endpoints_and_pagination(client):
    sid = client.get("/api/v1/series", params={"country": "XDM", "eligible_only": True}).json()[0]["series_id"]
    p1 = client.get("/api/v1/prices", params={"series_id": sid, "limit": 10}).json()
    p2 = client.get("/api/v1/prices", params={"series_id": sid, "limit": 10, "offset": 10}).json()
    assert p1["total"] == p2["total"] > 100 and p1["items"][0]["period"] < p2["items"][0]["period"]
    assert p1["synthetic"] is True and p1["snapshot_id"]
    m = next(x for x in client.get("/api/v1/markets", params={"country": "XDM"}).json() if x["weather_location_id"])
    w = client.get("/api/v1/weather", params={"location_id": m["weather_location_id"], "start": "2020-01"}).json()
    assert w["items"] and "proxy" in w["proxy_warning"] and w["units"]["precip_total_mm"] == "mm/month"
    ind = client.get("/api/v1/economic-indicators", params={"country": "XDM", "frequency": "M", "limit": 5}).json()
    assert ind["total"] > 5 and len(ind["items"]) == 5
    ag = client.get("/api/v1/agriculture", params={"country": "XDM"}).json()
    assert ag["items"][0]["item_name"].startswith("Maize")
    lag = client.get(f"/api/v1/series/{sid}/lagged-relationships").json()
    assert len(lag["items"]) == 7 and "not causal" in lag["caveat"]


def test_input_validation_and_safe_errors(client):
    assert client.get("/api/v1/prices", params={"country": "kenya"}).status_code == 422
    assert client.get("/api/v1/prices").status_code == 422
    assert client.get("/api/v1/prices", params={"series_id": "'; DROP TABLE x;--"}).status_code == 422
    r = client.get("/api/v1/experiments/does_not_exist")
    assert r.status_code == 404 and r.json()["error"] == "http_error"
    assert client.get("/api/v1/markets", params={"bbox": "a,b"}).status_code == 422
    assert "Traceback" not in client.get("/api/v1/experiments/../../etc").text


def test_unhandled_errors_return_generic_json_without_details(seeded_env):  # type: ignore[no-untyped-def]
    from market_almanac_api.main import create_app

    app = create_app()

    def boom() -> None:
        raise RuntimeError("secret-ish internal detail")

    app.add_api_route("/boom", boom)
    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json() == {"error": "internal_error", "detail": "An unexpected error occurred."}
    assert "secret-ish" not in r.text and "Traceback" not in r.text


def test_research_endpoints(client):
    exps = client.get("/api/v1/experiments").json()
    ids = {e["id"] for e in exps}
    assert {"demo_1_dm-maize", "demo_2_dm-rice"} <= ids
    assert all(e["synthetic"] for e in exps)
    verdicts = {e["id"]: e["verdict"] for e in exps}
    assert verdicts["demo_2_dm-rice"] == "not_improved"  # negative control
    d = client.get("/api/v1/experiments/demo_1_dm-maize").json()
    assert d["results"]["conclusion"]["causal_disclaimer"]
    bts = client.get("/api/v1/backtests", params={"experiment_id": "demo_1_dm-maize"}).json()
    assert {(b["task"], b["horizon"]) for b in bts} == {
        ("regression", 1),
        ("regression", 3),
        ("classification", 1),
        ("classification", 3),
    }
    bt = client.get(f"/api/v1/backtests/{bts[0]['id']}").json()
    assert bt["models"] and bt["folds"]
    comps = client.get(
        "/api/v1/model-comparisons", params={"experiment_id": "demo_1_dm-maize", "role": "primary"}
    ).json()
    assert len(comps) == 4
    preds = client.get(
        "/api/v1/predictions", params={"experiment_id": "demo_1_dm-maize", "models": "naive,ridge_B", "limit": 20}
    ).json()
    assert preds["total"] > 0 and {p["model"] for p in preds["items"]} <= {"naive", "ridge_B"}


def test_forecasts_have_status_and_cutoff(client):
    fc = client.get("/api/v1/forecasts").json()
    assert fc and all(f["synthetic"] for f in fc)
    for f in fc:
        assert f["status"] in ("issued", "withheld") and f["information_cutoff"] == f["origin_period"]
        if f["status"] == "issued":
            assert f["validation_status"].startswith("validated_")
        else:
            assert f["reason"]
    one = client.get(f"/api/v1/forecasts/{fc[0]['id']}").json()
    assert one["id"] == fc[0]["id"]


def test_reports_and_exports(client):
    md = client.get("/api/v1/reports/demo_1_dm-maize")
    assert md.status_code == 200 and "SYNTHETIC" in md.text and "Diebold" in md.text
    z = client.get("/api/v1/exports/demo_1_dm-maize", params={"format": "zip"})
    assert z.headers["content-type"] == "application/zip" and "SYNTHETIC" in z.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert {"results.json", "manifest.json", "predictions.csv", "report.md"} <= set(names)
    csv = client.get("/api/v1/exports/demo_1_dm-maize", params={"format": "csv"})
    assert csv.text.startswith("series_id,")
    man = client.get("/api/v1/exports/demo_1_dm-maize", params={"format": "manifest"}).json()
    assert man["random_seed"] == 42 and man["snapshots"]["prices"]["snapshot_id"]


def test_openapi_documents_versioned_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in (
        "/api/v1/prices",
        "/api/v1/weather",
        "/api/v1/forecasts",
        "/api/v1/model-comparisons",
        "/api/v1/exports/{experiment_id}",
        "/api/v1/data-quality",
    ):
        assert p in paths


def test_rate_limit(seeded_env, monkeypatch):
    from market_almanac.config import reset_settings_cache
    from market_almanac_api.main import create_app

    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "3")
    reset_settings_cache()
    c = TestClient(create_app())
    codes = [c.get("/api/v1/countries").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "100000")
    reset_settings_cache()


def test_reproducibility_manifest_on_disk(seeded_env):
    import json

    s = seeded_env["settings"]
    man = json.loads((s.experiments_dir / "demo_1_dm-maize" / "manifest.json").read_text())
    for k in (
        "snapshots",
        "config",
        "config_hash",
        "random_seed",
        "software_version",
        "retrospective_note",
        "eligible_series",
        "conclusion",
        "limitations",
    ):
        assert k in man
