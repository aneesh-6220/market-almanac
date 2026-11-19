"""The quality-report endpoints answer from database-side slices, identically to the old whole-document logic.

The live report is a 20.9 MB JSON document. Reading it whole on each fresh API process used most of a month's
metered database egress, so /data-quality, /series and /markets now filter and page inside the database. These tests
pin the responses to what the previous implementation computed from the full document, and fail if any request
selects the document itself.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(seeded_env):  # type: ignore[no-untyped-def]
    from market_almanac_api.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def full_report(seeded_env) -> tuple[str, str, dict[str, Any]]:  # type: ignore[no-untyped-def]
    from sqlalchemy import desc, select

    from market_almanac.config import get_settings
    from market_almanac.db import models as m
    from market_almanac.db.session import session_scope

    s = get_settings()
    with session_scope(s.database_url) as db:
        row = db.scalars(
            select(m.DataQualityReport)
            .where(m.DataQualityReport.mode == s.market_almanac_mode.value)
            .order_by(desc(m.DataQualityReport.created_at))
        ).first()
        assert row is not None
        return row.id, row.created_at.isoformat(), dict(row.report)


def _old_data_quality(rid: str, created: str, body: dict[str, Any], **q: Any) -> dict[str, Any]:
    """The pre-fix handler, verbatim in logic, applied to the whole document."""
    series_id, country = q.get("series_id"), q.get("country")
    eligible_only, limit, offset = q.get("eligible_only", False), q.get("limit", 1000), q.get("offset", 0)
    rep = {k: v for k, v in body.items() if k not in ("series", "extremes", "consistency_issues")}
    rep["id"], rep["created_at"], rep["synthetic"] = rid, created, True
    series, extremes = body.get("series", []), body.get("extremes", [])
    if series_id:
        series = [s for s in series if s["series_id"] == series_id]
    if country:
        series = [s for s in series if s["country_iso3"] == country]
    if eligible_only:
        series = [s for s in series if s["eligible"]]
    if series_id or country or eligible_only:
        keep = {s["series_id"] for s in series}
        extremes = [e for e in extremes if e["series_id"] in keep]
    issues = body.get("consistency_issues", [])
    if country:
        issues = [i for i in issues if f"{country}:" in i or f" {country} " in i]
    rep["series_total"], rep["extremes_total"], rep["consistency_issues_total"] = (
        len(series),
        len(extremes),
        len(issues),
    )
    rep["series"] = series[offset : offset + limit]
    rep["extremes"] = extremes[:1000]
    rep["consistency_issues"] = issues[:500]
    return rep


def test_data_quality_matches_the_whole_document_logic(client, full_report):  # type: ignore[no-untyped-def]
    rid, created, body = full_report
    assert body["series"] and body["extremes"], "the demo report must exercise both arrays"
    s0 = body["series"][0]
    with_extremes = next(e["series_id"] for e in body["extremes"])
    cases: list[dict[str, Any]] = [
        {},
        {"limit": 3},
        {"limit": 2, "offset": 5},
        {"offset": 10_000},
        {"country": s0["country_iso3"]},
        {"country": s0["country_iso3"], "eligible_only": True, "limit": 4, "offset": 1},
        {"eligible_only": True},
        {"series_id": s0["series_id"]},
        {"series_id": with_extremes},
        {"country": "ZZZ"},
        {"series_id": "ps_0000000000000000"},
    ]
    for q in cases:
        got = client.get("/api/v1/data-quality", params=q)
        assert got.status_code == 200, (q, got.text)
        assert got.json() == _old_data_quality(rid, created, body, **q), q


def test_series_and_markets_match_the_whole_document_logic(client, full_report):  # type: ignore[no-untyped-def]
    _, _, body = full_report
    country = body["series"][0]["country_iso3"]
    for eligible_only in (False, True):
        got = client.get("/api/v1/series", params={"country": country, "eligible_only": eligible_only}).json()
        want = [
            s["series_id"]
            for s in body["series"]
            if s["country_iso3"] == country and (s["eligible"] or not eligible_only)
        ]
        assert [s["series_id"] for s in got] == want
    eligible = {s["series_id"] for s in body["series"] if s["eligible"]}
    markets = client.get("/api/v1/markets", params={"country": country}).json()
    assert markets and sum(mk["eligible_series"] for mk in markets) == len(
        [s for s in body["series"] if s["series_id"] in eligible and s["country_iso3"] == country]
    )


def test_no_request_selects_the_whole_quality_document(client):  # type: ignore[no-untyped-def]
    from sqlalchemy import event

    from market_almanac.config import get_settings
    from market_almanac.db.session import get_engine
    from market_almanac_api import deps
    from market_almanac_api.quality_store import quality_store

    quality_store.clear()
    deps.cache.__init__()  # type: ignore[misc]  # a cold process: nothing about the report is held in memory
    engine = get_engine(get_settings().database_url)
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        for path, params in (
            ("/api/v1/data-quality", {}),
            ("/api/v1/data-quality", {"eligible_only": True}),
            ("/api/v1/series", {"country": "XDM"}),
            ("/api/v1/markets", {"country": "XDM"}),
        ):
            assert client.get(path, params=params).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    touching = [s for s in statements if "data_quality_reports" in s]
    assert touching
    whole = re.compile(r"data_quality_reports\.report\b|SELECT\s+(r\.)?report\b", re.I)
    assert not [s for s in touching if whole.search(s)], touching


def test_slices_are_cached_per_report_and_bounded():
    from market_almanac_api.quality_store import QualityStore

    store = QualityStore(max_rows=10, max_entries=3)
    calls: list[int] = []

    def make(n: int):  # type: ignore[no-untyped-def]
        def compute():  # type: ignore[no-untyped-def]
            calls.append(n)
            return list(range(n)), n

        return compute

    assert store._cached(("a",), make(4)) == [0, 1, 2, 3]
    assert store._cached(("a",), make(4)) == [0, 1, 2, 3] and calls == [4]
    store._cached(("big",), make(11))  # larger than the whole budget: answered, never retained
    store._cached(("big",), make(11))
    assert calls == [4, 11, 11]
    for k in ("b", "c", "d"):
        store._cached((k,), make(2))
    assert len(store._memo) <= 3 and store._rows <= 10
