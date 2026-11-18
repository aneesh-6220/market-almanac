"""Global ingestion: partitions, resumable runs, provider failure isolation, QC and the coverage registry."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pandas as pd
import pytest
from pydantic import SecretStr

from market_almanac.globaldata.discovery import summarise_discovery
from market_almanac.globaldata.ingest import RunLog, execute_run, new_run
from market_almanac.globaldata.partitions import PartitionStore, check_iso3, observation_hash
from market_almanac.globaldata.qc import summarise_partition
from market_almanac.globaldata.registry import MIN_ELIGIBLE_SERIES, build_registry, classify
from market_almanac.providers.base import ProviderSchemaError
from market_almanac.providers.hdx_hapi import PAGE_LIMIT, HdxHapiProvider, normalize_food_prices
from tests.conftest import fixture_json, run


def _prices(country: str = "KEN", price_scale: float = 1.0) -> pd.DataFrame:
    raw = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"]
    raw = [{**r, "location_code": country, "price": r["price"] * price_scale} for r in raw]
    df, _, _ = normalize_food_prices(raw, pd.Timestamp("2026-11-01", tz="UTC"))
    return df


# ---------------------------------------------------------------- partitions


def test_partition_write_is_idempotent_and_detects_revisions(tmp_path: Path):
    store = PartitionStore(tmp_path, "live")
    a = store.write("prices", "KEN", _prices(), provider="hdx_hapi")
    assert a.status == "written" and a.manifest.revision == "initial"
    # a re-download that differs only in retrieval time is not a new snapshot
    again = _prices().assign(retrieved_at=pd.Timestamp("2026-11-17", tz="UTC"))
    b = store.write("prices", "KEN", again, provider="hdx_hapi")
    assert b.status == "unchanged" and b.manifest.snapshot_id == a.manifest.snapshot_id
    # a provider revision creates a new snapshot and leaves the old one byte-identical
    old_bytes = store.path("prices", "KEN", a.manifest.snapshot_id).read_bytes()
    revised = _prices()
    revised.loc[revised.index[0], "price"] *= 1.5
    c = store.write("prices", "KEN", revised, provider="hdx_hapi")
    assert c.status == "written" and c.manifest.revision == "changed"
    assert c.manifest.parent_snapshot_id == a.manifest.snapshot_id
    assert c.manifest.diff["revised"] == 1 and c.manifest.diff["added"] == 0
    assert store.path("prices", "KEN", a.manifest.snapshot_id).read_bytes() == old_bytes
    assert len(store.list_snapshots("prices", "KEN")) == 2
    # old snapshot stays readable by id; integrity verification passes
    assert len(store.read("prices", "KEN", a.manifest.snapshot_id, verify=True)) == len(_prices())


def test_observation_hash_ignores_row_order_and_retrieval_time():
    df = _prices()
    shuffled = df.sample(frac=1, random_state=1).assign(retrieved_at=pd.Timestamp("2030-01-01", tz="UTC"))
    assert observation_hash(df, ("series_id", "period")) == observation_hash(shuffled, ("series_id", "period"))


def test_partition_ignores_interrupted_writes_and_rejects_bad_paths(tmp_path: Path):
    store = PartitionStore(tmp_path, "live")
    store.write("prices", "KEN", _prices(), provider="hdx_hapi")
    # simulate a crash mid-write: a hidden temp directory with a partial file
    tmp = tmp_path / "partitions" / "prices" / "KEN" / ".tmp_20990101T000000_abcdef"
    tmp.mkdir()
    (tmp / "data.parquet").write_bytes(b"partial")
    assert len(store.list_snapshots("prices", "KEN")) == 1
    assert store.clean_temp() == 1 and not tmp.exists()
    for bad in ("../x", "ke", "KEN/..", "", "K3N"):
        with pytest.raises(ValueError):
            check_iso3(bad)
    with pytest.raises(ValueError):
        store.read("prices", "KEN", "../../etc/passwd")


def test_failed_write_leaves_previous_snapshot_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = PartitionStore(tmp_path, "live")
    first = store.write("prices", "KEN", _prices(), provider="hdx_hapi").manifest

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError):
        store.write("prices", "KEN", _prices(price_scale=2.0), provider="hdx_hapi")
    monkeypatch.undo()
    assert [m.snapshot_id for m in store.list_snapshots("prices", "KEN")] == [first.snapshot_id]
    assert not list((tmp_path / "partitions" / "prices" / "KEN").glob(".tmp_*"))


# ---------------------------------------------------------------- runs


def test_run_isolates_country_failures_and_resumes(tmp_path: Path):
    store, runlog = PartitionStore(tmp_path / "lake", "live"), RunLog(tmp_path / "global")
    calls: list[str] = []
    outage = {"UGA"}

    async def fetch(iso3: str) -> tuple[pd.DataFrame, list[str], int]:
        calls.append(iso3)
        if iso3 in outage:
            raise ConnectionError("provider outage")
        return _prices(iso3), [], 1

    state = new_run(["KEN", "UGA", "TZA"])
    state = asyncio.run(execute_run(state, store, runlog, fetch, qc=False))
    assert state.countries["UGA"].status == "failed" and "outage" in (state.countries["UGA"].error or "")
    assert state.countries["KEN"].status == state.countries["TZA"].status == "succeeded"
    # the state file on disk reflects the outcome (a crashed process can resume from it)
    assert runlog.load(state.run_id).summary() == {"succeeded": 2, "failed": 1}

    outage.clear()
    calls.clear()
    resumed = asyncio.run(execute_run(runlog.load(state.run_id), store, runlog, fetch, qc=False))
    assert calls == ["UGA"]  # completed countries are not fetched again
    assert resumed.summary() == {"succeeded": 3}


def test_run_resumes_after_interruption(tmp_path: Path):
    """A process killed mid-run leaves 'running' entries; resuming retries them."""
    store, runlog = PartitionStore(tmp_path / "lake", "live"), RunLog(tmp_path / "global")
    state = new_run(["KEN", "UGA"])
    state.countries["KEN"].status, state.countries["KEN"].attempts = "running", 1
    runlog.save(state)

    async def fetch(iso3: str) -> tuple[pd.DataFrame, list[str], int]:
        return _prices(iso3), [], 1

    out = asyncio.run(execute_run(runlog.load(state.run_id), store, runlog, fetch, qc=False))
    assert out.summary() == {"succeeded": 2} and out.countries["KEN"].attempts == 2


def test_run_rejects_invalid_country_codes():
    with pytest.raises(ValueError):
        new_run(["KEN", "../../x"])


# ---------------------------------------------------------------- provider guards


def test_hdx_duplicate_page_is_refused(make_http, settings_factory):
    rows = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"]
    page = [{**rows[i % len(rows)], "market_code": str(i)} for i in range(PAGE_LIMIT)]
    http, _, _ = make_http(lambda req: httpx.Response(200, json={"data": page}))  # offset ignored upstream
    p = HdxHapiProvider(http, settings_factory(hdx_hapi_app_identifier=SecretStr("dGVzdDp0QGV4YW1wbGUub3Jn")))
    with pytest.raises(ProviderSchemaError, match="repeated"):
        run(p.fetch("food_prices", country_iso3="KEN"))


def test_hdx_schema_drift_detected_beyond_first_rows():
    raw = fixture_json("hdx_hapi", "food_prices_ken_134_2024.json")["data"]
    drifted = [*raw[:10], {k: v for k, v in raw[10].items() if k != "currency_code"}]
    with pytest.raises(ProviderSchemaError):
        normalize_food_prices(drifted, pd.Timestamp.now(tz="UTC"))


# ---------------------------------------------------------------- QC and registry


def test_qc_flags_future_dates_without_deleting_rows():
    df = _prices()
    ok = summarise_partition(df)
    assert ok["validated"] and ok["rows"] == len(df) and ok["future_dated"] == 0
    bad = df.copy()
    bad.loc[bad.index[0], "period"] = pd.Timestamp("2031-01-01")
    out = summarise_partition(bad)
    assert not out["validated"] and out["future_dated"] == 1 and out["rows"] == len(df)


def test_classify_status_ladder():
    base = {"discovered": True, "stored": True, "validated": True, "evaluated": False, "last_attempt_failed": False}
    assert classify(**{**base, "discovered": False, "stored": False}, eligible_series=0) == "unsupported"
    assert classify(**{**base, "stored": False}, eligible_series=0) == "discoverable"
    assert classify(**{**base, "stored": False, "last_attempt_failed": True}, eligible_series=0) == (
        "temporarily_unavailable"
    )
    # a failed refresh does not demote a country whose earlier snapshot is stored
    assert classify(**{**base, "last_attempt_failed": True}, eligible_series=50) == "research_eligible"
    assert classify(**{**base, "validated": False}, eligible_series=50) == "ingested"
    assert classify(**base, eligible_series=MIN_ELIGIBLE_SERIES - 1) == "validated"
    assert classify(**{**base, "evaluated": True}, eligible_series=MIN_ELIGIBLE_SERIES) == "forecast_evaluated"


def test_registry_reports_gaps_rather_than_filling_them():
    disc = summarise_discovery(
        [
            {"location_code": "KEN", "location_name": "Kenya", "subcategory": "food-prices-market-monitor"},
            {"location_code": "UGA", "location_name": "Uganda", "subcategory": "food-prices-market-monitor"},
            {"location_code": "FRA", "location_name": "France", "subcategory": "conflict-events"},
        ],
        [{"location_code": "KEN", "lat": -1.2, "lon": 36.8}, {"location_code": "KEN", "lat": None, "lon": None}],
    )
    assert set(disc["countries"]) == {"KEN", "UGA"}
    assert disc["countries"]["KEN"]["markets_with_coordinates"] == 1
    part = {"row_count": 100, "snapshot_id": "s", "qc": {"validated": True, "eligible_series": 12, "markets": 3}}
    reg = build_registry(
        universe={"KEN": "Kenya", "UGA": "Uganda", "FRA": "France"},
        discovery=disc,
        partitions={"KEN": part},
        last_attempts={"UGA": {"status": "failed", "error": "timeout"}},
        weather_countries={},
        macro_countries=set(),
        agriculture_countries=set(),
        evaluations={},
    )
    by = {r["country_iso3"]: r for r in reg["countries"]}
    assert by["KEN"]["status"] == "research_eligible"
    assert by["UGA"]["status"] == "temporarily_unavailable" and by["UGA"]["observations"] is None
    assert by["FRA"]["status"] == "unsupported" and by["FRA"]["price_sources"] == []
    assert by["KEN"]["environment"]["chirps_v3_integrated"] is False
    assert reg["totals"]["countries_with_observations"] == 1


def test_registry_counts_study_primaries_but_not_placebos(settings_factory):
    """A workbench study's primary analysis marks its country evaluated; a placebo variant alone does not."""
    import json

    from market_almanac.globaldata.registry import collect_inputs

    s = settings_factory(market_almanac_mode="live")
    exp = Path(s.data_dir) / "studies" / "live" / "atlas" / "experiments"
    for name, iso in (
        ("atlas__ETH_67_KG_R_ETB__primary", "ETH"),
        ("atlas__UGA_67_KG_R_UGX__weather_time_shift_60", "UGA"),
    ):
        (exp / name).mkdir(parents=True)
        body = {"status": "completed", "experiment_id": name, "config": {"country_iso3": iso, "study": "atlas"}}
        (exp / name / "results.json").write_text(json.dumps(body))
    evals = collect_inputs(s)["evaluations"]
    assert [e["id"] for e in evals["ETH"]] == ["atlas__ETH_67_KG_R_ETB__primary"]
    assert "UGA" not in evals
