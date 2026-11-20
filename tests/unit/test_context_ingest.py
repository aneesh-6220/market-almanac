"""Economic-context ingestion: IMF validation rules, Pink Sheet parsing, refresh, snapshots and the licence policy.

All sources are synthetic (``tests/context_support.py``): they reproduce structures seen in the real sources, not their
values, because the sources' redistribution terms are not confirmed.
"""

from __future__ import annotations

import asyncio
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_almanac.context import imf_ingest as imf
from market_almanac.context import pinksheet as pink
from market_almanac.context.coverage import coverage_matrix
from market_almanac.context.reference import benchmark_mapping, benchmark_table, regime_for, regimes
from market_almanac.context.refresh import refresh
from market_almanac.context.release import (
    build_context_bundle,
    check_against,
    install_context,
    is_installed,
    series_hashes,
)
from market_almanac.context.store import ContextSnapshot, ContextStore, ContextStoreError
from market_almanac.data.public_bundle import BundleError
from tests import context_support as cs

RETRIEVED = datetime(2026, 11, 20, tzinfo=UTC)


def _parse(concept: str, items: list[dict[str, Any]]) -> imf.ParsedConcept:
    c = imf.CONCEPT_BY_NAME[concept]
    return imf.parse_concept(cs.sdmx_xml(c.flow, items), c, RETRIEVED)


# --- IMF parsing and validation ---------------------------------------------------------------------------------


def test_empty_observations_are_missing_not_zero() -> None:
    p = _parse("cpi_food", cs.world()["cpi_food"])
    ner = p.observations[p.observations["series_key"] == "imf.cpi_food.NER"]
    assert ner.empty  # an all-empty series yields no observations...
    row = next(r for r in p.series if r["series_key"] == "imf.cpi_food.NER")
    assert row["n_obs"] == 0 and row["n_source_empty"] == len(cs.months(cs.START, cs.END))  # ...and says why


def test_future_dated_value_is_rejected_not_kept() -> None:
    p = _parse("fx_period_avg", cs.world()["fx_period_avg"])
    zwe = p.observations[p.observations["series_key"] == "imf.fx_period_avg.ZWE"]
    assert pd.Timestamp("2027-03-01") not in set(zwe["period"])
    rej = [r for r in p.rejected if r["reason"] == "future_period"]
    assert [(r["series_key"], r["period"]) for r in rej] == [("imf.fx_period_avg.ZWE", "2027-03")]


def test_duplicate_month_removes_every_copy() -> None:
    p = _parse("cpi_headline", cs.world()["cpi_headline"])
    zwe = p.observations[p.observations["series_key"] == "imf.cpi_headline.ZWE"]
    assert pd.Timestamp("2020-05-01") not in set(zwe["period"])  # ambiguous month: neither value is trusted
    assert any(r["reason"] == "duplicate_period" for r in p.rejected)


def test_unspliced_rebase_is_flagged_as_a_base_break() -> None:
    p = _parse("cpi_headline", cs.world()["cpi_headline"])
    lby = next(r for r in p.series if r["series_key"] == "imf.cpi_headline.LBY")
    assert lby["base_breaks"] == ["2025-01"]
    ken = next(r for r in p.series if r["series_key"] == "imf.cpi_headline.KEN")
    assert ken["base_breaks"] == []


def test_non_monthly_and_non_positive_and_bad_country_rows_are_rejected() -> None:
    bad = cs.series(
        "KEN",
        {"2020-01": 100.0, "2020-02": 0.0, "2020-03": -5.0},
        obs_extra=[("2020", 105.0, {}), ("2020-Q1", 106.0, {})],
    )
    p = _parse("cpi_headline", [bad, cs.series("G20", {"2020-01": 1.0})])
    reasons = sorted(r["reason"] for r in p.rejected)
    assert reasons == [
        "non_country_code",
        "non_monthly_period",
        "non_monthly_period",
        "non_positive_level",
        "non_positive_level",
    ]
    assert list(p.observations["period"]) == [pd.Timestamp("2020-01-01")]


def test_malformed_xml_raises() -> None:
    with pytest.raises(Exception, match=r"malformed|no DataSet"):
        imf.parse_concept("<not-sdmx", imf.CONCEPTS[0], RETRIEVED)


def test_dataset_vintage_is_recorded_separately_from_retrieval() -> None:
    p = _parse("cpi_headline", cs.world()["cpi_headline"][:1])
    assert p.source["publication_date"].startswith("2026-11-19")
    assert "retrieved_at" not in p.source  # the retrieval time is added by the refresh, not conflated with the vintage


# --- Pink Sheet -------------------------------------------------------------------------------------------------


def test_pink_workbook_extracts_mapped_benchmarks_with_units(tmp_path: Path) -> None:
    pk = pink.parse_workbook(cs.pink_workbook(tmp_path / "pink.xlsx"))
    assert {s["benchmark_id"] for s in pk.series} == set(benchmark_table()["benchmarks"])
    assert pk.updated_on == "November 3, 2026"
    rice = next(s for s in pk.series if s["benchmark_id"] == "rice_thai_5")  # header carried a footnote asterisk
    assert rice["unit"] == "USD per metric ton" and rice["definition"]["text"].startswith("Rice (Thailand), 5% broken")


def test_pink_rejects_value_errors_and_zeros_and_keeps_the_rest(tmp_path: Path) -> None:
    p = cs.pink_workbook(tmp_path / "p.xlsx", overrides={("maize", "2015-03"): "#VALUE!", ("palm_oil", "2016-04"): 0})
    pk = pink.parse_workbook(p)
    assert sorted((r["series_key"], r["reason"]) for r in pk.rejected) == [
        ("wb.pink.maize", "unparseable"),
        ("wb.pink.palm_oil", "non_positive"),
    ]
    maize = pk.observations[pk.observations["series_key"] == "wb.pink.maize"]
    assert pd.Timestamp("2015-03-01") not in set(maize["period"]) and len(maize) == pk.n_months - 1


def test_pink_discontinued_series_ends_without_being_filled(tmp_path: Path) -> None:
    pk = pink.parse_workbook(cs.pink_workbook(tmp_path / "p.xlsx"))
    sorg = pk.observations[pk.observations["series_key"] == "wb.pink.sorghum"]
    assert sorg["period"].max() == pd.Timestamp("2020-08-01")


def test_pink_changed_unit_fails_loudly(tmp_path: Path) -> None:
    p = cs.pink_workbook(tmp_path / "p.xlsx", unit_override={"rice_thai_5": "($/kg)"})
    with pytest.raises(pink.PinkSheetError, match="unit"):
        pink.parse_workbook(p)


def test_pink_missing_benchmark_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(pink.PinkSheetError, match="no longer in"):
        pink.parse_workbook(cs.pink_workbook(tmp_path / "p.xlsx", drop={"beef"}))


def test_workbook_link_discovery() -> None:
    assert pink.find_workbook_url(cs.PINK_PAGE).endswith("CMO-Historical-Data-Monthly.xlsx")
    with pytest.raises(pink.PinkSheetError):
        pink.find_workbook_url("<html>moved</html>")


# --- reference tables -------------------------------------------------------------------------------------------


def test_reference_tables_validate_and_resolve() -> None:
    assert regimes()["version"]
    assert [e["id"] for e in regime_for("SEN")] == ["xof"]
    assert regime_for("KEN") == []  # unlisted is "not classified", never assumed floating
    imported = benchmark_mapping("Rice (imported)")
    assert imported["confidence"] == "medium" and "rice_thai_5" in imported["benchmarks"]
    assert benchmark_mapping("Rice (local)")["confidence"] == "none"
    unknown = benchmark_mapping("Millet")
    assert unknown["confidence"] == "none" and unknown["benchmarks"] == []
    assert all(m["confidence"] != "high" for m in benchmark_table()["mappings"])  # by design


# --- refresh end to end (scripted HTTP) -------------------------------------------------------------------------


@pytest.fixture
def refreshed(tmp_path: Path, make_http: Any) -> Any:
    wb = cs.pink_workbook(tmp_path / "src" / "pink.xlsx")
    http, rec, _ = make_http(cs.handler(cs.world(), wb))
    store = ContextStore(tmp_path / "store")
    work = tmp_path / "work"
    out = asyncio.run(refresh(store, http, work, pause=0, now=datetime(2026, 11, 20, tzinfo=UTC)))
    return store, out, work, http, rec, wb


def test_refresh_writes_a_verified_snapshot(refreshed: Any) -> None:
    store, out, *_ = refreshed
    assert out.status == "written" and out.manifest["revision"] == "initial"
    assert store.verify(out.snapshot_id) == []
    snap = ContextSnapshot(store.path(out.snapshot_id))
    assert snap.has_data and set(snap.countries()) == {"KEN", "NER", "LBY", "ZWE", "SEN"}
    assert snap.source("imf", "CPI")["licence"]["redistribution"] == "unconfirmed"
    assert snap.source("world_bank")["workbook_sha256"]
    assert out.manifest["semantics"]["release_lags_are_assumptions"] is True


def test_refresh_is_idempotent_and_writes_nothing_new(refreshed: Any, tmp_path: Path, make_http: Any) -> None:
    store, first, _, _, _, wb = refreshed
    http, *_ = make_http(cs.handler(cs.world(), wb))
    again = asyncio.run(refresh(store, http, tmp_path / "work2", pause=0, now=datetime(2026, 12, 1, tzinfo=UTC)))
    assert again.status == "unchanged" and again.snapshot_id == first.snapshot_id
    assert store.snapshot_ids() == [first.snapshot_id]  # a different retrieval time alone is not a new snapshot


def test_refresh_resumes_from_completed_retrievals(refreshed: Any, make_http: Any, tmp_path: Path) -> None:
    store, _, work, _, _, wb = refreshed
    http, rec, _ = make_http(cs.handler(cs.world(), wb))
    asyncio.run(refresh(store, http, work, pause=0, resume=True, now=datetime(2026, 11, 21, tzinfo=UTC)))
    imf_calls = [r for r in rec.requests if "api.imf.org" in str(r.url)]
    assert imf_calls == []  # every IMF response was reused from the work directory


def test_refresh_retries_a_busy_server(tmp_path: Path, make_http: Any) -> None:
    wb = cs.pink_workbook(tmp_path / "p.xlsx")
    http, _, sleeps = make_http(cs.handler(cs.world(), wb, fail_first={"cpi_food": 2}), retries=3)
    out = asyncio.run(refresh(ContextStore(tmp_path / "s"), http, tmp_path / "w", pause=0))
    assert out.status == "written" and len(sleeps) >= 2  # backed off twice, then succeeded


def test_changed_vintage_creates_a_new_snapshot_with_a_revision_diff(
    refreshed: Any, make_http: Any, tmp_path: Path
) -> None:
    store, first, _, _, _, wb = refreshed
    w = cs.world()
    ken = w["cpi_headline"][0]
    period, value, extra = ken["obs"][10]
    ken["obs"][10] = (period, value * 1.01, extra)  # the IMF revised one month
    ken["obs"].append(("2026-10", 999.0, {"REFERENCE_PERIOD": "2010"}))  # and added one
    http, *_ = make_http(cs.handler(w, wb))
    second = asyncio.run(refresh(store, http, tmp_path / "work3", pause=0, now=datetime(2026, 11, 25, tzinfo=UTC)))
    assert second.status == "written" and second.manifest["parent_snapshot_id"] == first.snapshot_id
    d = second.manifest["revision_diff"]
    assert (d["added"], d["removed"], d["revised"]) == (1, 0, 1)
    assert d["revised_by_concept"] == {"cpi_headline": 1}
    # the first snapshot is untouched and still verifies
    assert store.verify(first.snapshot_id) == [] and store.snapshot_ids() == [first.snapshot_id, second.snapshot_id]


def test_snapshot_verification_detects_tampering(refreshed: Any) -> None:
    store, out, *_ = refreshed
    f = store.path(out.snapshot_id) / "observations.parquet"
    f.write_bytes(f.read_bytes()[:-8] + b"tampered")
    assert any("SHA-256" in p for p in store.verify(out.snapshot_id))


def test_incomplete_write_never_leaves_a_snapshot(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "s")
    with pytest.raises(ContextStoreError):
        store.write_snapshot(
            pd.DataFrame(columns=["series_key", "period", "value", "reference_period", "derivation"]), [], [], []
        )
    assert store.snapshot_ids() == [] and not any(p.name.startswith(".tmp-") for p in (tmp_path / "s").glob("*"))


def test_reading_a_missing_snapshot_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ContextStoreError):
        ContextStore(tmp_path).manifest("20260101T000000_abcdef")
    with pytest.raises(ContextStoreError):
        ContextStore(tmp_path).path("../etc")


# --- coverage ---------------------------------------------------------------------------------------------------


def test_coverage_states_what_is_missing(refreshed: Any) -> None:
    store, out, *_ = refreshed
    m = coverage_matrix(ContextSnapshot(store.path(out.snapshot_id))).set_index("country")
    assert m.loc["KEN", "usable"] == "full"
    assert m.loc["NER", "cpi_food_state"] == "none" and m.loc["NER", "usable"].startswith("headline CPI + FX")
    assert m.loc["SEN", "regime"] == "xof" and m.loc["KEN", "regime"] == "not classified"
    assert m.loc["LBY", "cpi_headline_state"] == "stale"  # ends 2025-06, months before the newest series


# --- licence policy and the artefact ----------------------------------------------------------------------------


def _bundle_dir(refreshed: Any, tmp_path: Path) -> tuple[Path, ContextStore]:
    store, *_ = refreshed
    data = tmp_path / "data"
    (data / "context").mkdir(parents=True)
    (data / "context" / "live").symlink_to(store.root, target_is_directory=True)
    return data, store


def test_public_bundle_withholds_unconfirmed_observations(refreshed: Any, tmp_path: Path) -> None:
    data, _ = _bundle_dir(refreshed, tmp_path)
    res = build_context_bundle(data, "live", tmp_path / "dist")
    assert res["data_included"] == "none" and res["withheld_providers"] == ["imf", "world_bank"]
    with tarfile.open(res["archive"]) as t:
        names = t.getnames()
        assert not any(n.endswith("observations.parquet") for n in names)
        retrieval = t.extractfile(next(n for n in names if n.endswith("RETRIEVAL.md"))).read().decode()  # type: ignore[union-attr]
        rejected = json.loads(t.extractfile(next(n for n in names if n.endswith("rejected.json"))).read())  # type: ignore[union-attr]
        hashes = json.loads(t.extractfile(next(n for n in names if n.endswith("series_hashes.json"))).read())  # type: ignore[union-attr]
    assert "market-almanac context refresh" in retrieval and "terms" in retrieval.lower()
    assert all(r["value"] is None for r in rejected)  # a rejected raw value is still a source value
    assert len(hashes) > 10 and all(len(h) == 64 for h in hashes.values())


def test_metadata_only_install_is_not_a_data_install(refreshed: Any, tmp_path: Path, settings_factory: Any) -> None:
    data, _ = _bundle_dir(refreshed, tmp_path)
    res = build_context_bundle(data, "live", tmp_path / "dist")
    target = tmp_path / "fresh"
    s = settings_factory(data_dir=target, market_almanac_mode="live")
    info = install_context(s, res["archive"], res["sha256"])
    assert info["has_data"] is False and not is_installed(s)  # honest: nothing to compute with
    assert ContextStore.for_settings(s).latest_id(with_data=True) is None
    assert ContextStore.for_settings(s).verify(info["snapshot_id"]) == []


def test_complete_bundle_installs_and_matches_series_hashes(
    refreshed: Any, tmp_path: Path, settings_factory: Any
) -> None:
    data, store = _bundle_dir(refreshed, tmp_path)
    res = build_context_bundle(data, "live", tmp_path / "dist", include_unconfirmed=True)
    assert res["data_included"] == "full"
    s = settings_factory(data_dir=tmp_path / "fresh", market_almanac_mode="live")
    info = install_context(s, res["archive"], res["sha256"])
    assert info["has_data"] and is_installed(s)
    local = ContextSnapshot(ContextStore.for_settings(s).path(info["snapshot_id"]))
    ref = series_hashes(ContextSnapshot(store.path(info["snapshot_id"])).observations())
    cmp = check_against(local, ref)
    assert cmp["different"] == [] and cmp["missing_locally"] == [] and len(cmp["identical"]) == len(ref)


def test_install_requires_the_expected_hash(refreshed: Any, tmp_path: Path, settings_factory: Any) -> None:
    data, _ = _bundle_dir(refreshed, tmp_path)
    res = build_context_bundle(data, "live", tmp_path / "dist")
    s = settings_factory(data_dir=tmp_path / "fresh", market_almanac_mode="live")
    with pytest.raises(BundleError, match="SHA-256"):
        install_context(s, res["archive"], "0" * 64)


def test_a_series_hash_changes_when_any_value_changes() -> None:
    a = pd.DataFrame(
        {"series_key": ["k"] * 3, "period": pd.date_range("2020-01-01", periods=3, freq="MS"), "value": [1.0, 2.0, 3.0]}
    )
    b = a.copy()
    b.loc[1, "value"] = 2.0000001
    assert series_hashes(a) != series_hashes(b) and series_hashes(a) == series_hashes(a.copy())
