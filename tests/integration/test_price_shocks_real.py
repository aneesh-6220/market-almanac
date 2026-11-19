"""Price Shock Investigator over the archived global WFP data (95 countries, offline).

Needs the pinned ``global-prices-v2`` snapshot and a shock catalog built from it (``market-almanac global shocks``)
in ``MARKET_ALMANAC_REAL_DATA_DIR`` or ``data/``; otherwise these tests skip. Expectations come from the Parquet
files read independently of the API, or from fixed properties of the method, never from numbers copied from the
API under test.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from market_almanac.globaldata.release import pinned_release
from market_almanac.globaldata.shocks import SHOCK_CATALOG, SHOCK_MANIFEST
from tests.global_support import deployment
from tests.integration.test_global_prices_real import REAL, partition


def _catalog() -> Path | None:
    if REAL is None:
        return None
    d = REAL / "public" / "live"
    try:
        man = json.loads((d / SHOCK_MANIFEST).read_text())
    except (OSError, ValueError):
        return None
    pins = {c: v["snapshot_id"] for c, v in man.get("countries", {}).items()}
    return d / SHOCK_CATALOG if pins == pinned_release()["snapshots"] else None


CATALOG = _catalog()
pytestmark = pytest.mark.skipif(CATALOG is None, reason="shock catalog for the pinned snapshot not installed")

# The worked example linked from /investigate (apps/web/src/app/investigate/example.ts).
EXAMPLE = {"series": "ps_f0d5ea3ff6ef122d", "event": "2024-06", "start": "2022-06", "end": "2025-06"}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    assert REAL is not None
    with deployment(REAL, tmp_path_factory.mktemp("shockdb")) as c:
        yield c


def sql(q: str, params: list | None = None) -> list[tuple]:
    return duckdb.connect().execute(q.replace("CATALOG", f"read_parquet('{CATALOG}')"), params or []).fetchall()


def raw_price(iso3: str, sid: str, month: str) -> float:
    """The first valid record of the month, read straight from the partition (the API's monthly rule)."""
    rows = (
        duckdb.connect()
        .execute(
            f"SELECT price, quality_flags FROM read_parquet('{partition(iso3)}') "
            "WHERE series_id = ? AND strftime(period, '%Y-%m') = ? ORDER BY period",
            [sid, month],
        )
        .fetchall()
    )
    valid = [p for p, f in rows if p and p > 0 and not (f or "")]
    assert valid, (sid, month)
    return float(valid[0])


# --- the catalog ------------------------------------------------------------------------------------------


def test_catalog_is_consistent_with_the_method():
    kinds = dict(sql("SELECT kind, count(*) FROM CATALOG GROUP BY 1"))
    assert set(kinds) == {"unusual", "large_typical", "withheld"} and kinds["unusual"] > 1000
    # an unusual episode always reached the trigger; a withheld one is never scored
    assert sql("SELECT count(*) FROM CATALOG WHERE kind = 'unusual' AND abs(peak_z) < 2")[0][0] == 0
    assert sql("SELECT count(*) FROM CATALOG WHERE kind = 'withheld' AND peak_z IS NOT NULL")[0][0] == 0
    assert sql("SELECT count(*) FROM CATALOG WHERE kind = 'withheld' AND withheld_reason IS NULL")[0][0] == 0
    # a large-but-typical episode is large and within the series' range
    assert sql("SELECT count(*) FROM CATALOG WHERE kind = 'large_typical' AND abs(peak_yoy_pct) < 0.25")[0][0] == 0
    assert sql("SELECT count(*) FROM CATALOG WHERE kind = 'large_typical' AND abs(peak_z) >= 2")[0][0] == 0
    # extent is only claimed with enough assessable peers
    bad = "SELECT count(*) FROM CATALOG WHERE extent IN ('widespread', 'local', 'mixed') AND peer_assessable < 3"
    assert sql(bad)[0][0] == 0
    assert sql('SELECT count(*) FROM CATALOG WHERE start > peak OR peak > "end"')[0][0] == 0


def test_discovery_hides_data_concerns_and_non_food_unless_asked(client):
    assert sql("SELECT count(*) FROM CATALOG WHERE kind = 'unusual' AND data_concern")[0][0] > 0
    page = client.get("/api/v1/shocks", params={"limit": 100, "sort": "unusual"}).json()
    assert page["items"] and not any(i["data_concern"] for i in page["items"])
    assert not any(i.get("commodity_category") == "non-food" for i in page["items"])
    assert page["stale_countries"] == []
    wide = client.get("/api/v1/shocks", params={"limit": 100, "include_data_concerns": True}).json()
    assert wide["total"] > page["total"]


def test_discovery_is_bounded_and_fast(client):
    worst = 0.0
    for params in (
        {},
        {"kind": "all", "direction": "any", "sort": "recent"},
        {"q": "rice", "sort": "change"},
        {"kind": "withheld", "direction": "any", "offset": 9_900, "limit": 100},
        {"country": "NER", "extent": "widespread", "include_non_food": True},
    ):
        t = time.perf_counter()
        r = client.get("/api/v1/shocks", params=params)
        worst = max(worst, time.perf_counter() - t)
        assert r.status_code == 200, (params, r.text)
        assert len(r.json()["items"]) <= 100 and len(r.content) < 160_000  # ~1.3 kB a row; the UI asks for 25
    assert worst < 3.0, worst  # a laptop; Render's 0.1 vCPU is slower but the work is the same bounded query


# --- investigations ---------------------------------------------------------------------------------------


def test_worked_example_matches_the_raw_records_and_reproduces(client):
    sid = EXAMPLE["series"]
    q = {k: EXAMPLE[k] for k in ("event", "start", "end")}
    d = client.get(f"/api/v1/investigations/{sid}", params=q).json()
    assert d["subject"]["country_iso3"] == "NER" and d["subject"]["currency"] == "XOF"
    # the price and 12-month change come from the stored records
    now, year_ago = raw_price("NER", sid, "2024-06"), raw_price("NER", sid, "2023-06")
    assert d["magnitude"]["event_price"] == pytest.approx(now)
    assert d["magnitude"]["event_yoy_pct"] == pytest.approx(now / year_ago - 1)
    ep = d["episode"]
    assert ep["kind"] == "unusual" and not ep["data_concern"] and ep["duration_months"] >= 6
    assert d["unusualness"]["label"] == "unusual" and d["unusualness"]["stable"]
    assert d["peers"]["extent"]["class"] == "widespread" and d["peers"]["extent"]["n_assessable"] >= 10
    for p in d["peers"]["rows"]:  # comparisons never cross units, price types or currencies
        assert (p["commodity_name"], p["unit"], p["price_type"]) == ("Rice (imported)", "KG", "Retail")
    assert {m["key"]: m["status"] for m in d["evidence"]["mechanisms"]}["policy"] == "cannot_be_assessed"
    assert all(x["inference"] != "causal" for x in d["evidence"]["observed_facts"] + d["evidence"]["quantitative"])
    again = client.get(f"/api/v1/investigations/{sid}", params=q).json()
    assert json.dumps(again, sort_keys=True) == json.dumps(d, sort_keys=True)
    md = client.get(f"/api/v1/investigations/{sid}/export", params={**q, "format": "md"}).text
    assert d["config_id"] in md and d["config"]["snapshot_id"] in md and "+53.3%" in md


def test_a_large_change_that_is_typical_for_its_market_is_not_called_unusual(client):
    sid, peak = sql(
        "SELECT series_id, strftime(peak, '%Y-%m') FROM CATALOG WHERE kind = 'large_typical' AND direction = 'up' "
        "AND stable AND NOT data_concern AND peak_yoy_pct > 0.5 ORDER BY series_id, peak LIMIT 1"
    )[0]
    d = client.get(f"/api/v1/investigations/{sid}", params={"event": peak}).json()
    assert d["magnitude"]["large_nominal"] and d["magnitude"]["event_yoy_pct"] > 0.5
    assert d["unusualness"]["status"] == "ok" and d["unusualness"]["label"] == "typical"
    assert any("not unusual for this market" in x["text"] for x in d["evidence"]["quantitative"])


def test_an_unassessable_movement_is_withheld_with_a_reason(client):
    sid, peak, reason = sql(
        "SELECT series_id, strftime(peak, '%Y-%m'), withheld_reason FROM CATALOG WHERE kind = 'withheld' "
        "AND withheld_reason = 'short_history' ORDER BY series_id, peak LIMIT 1"
    )[0]
    d = client.get(f"/api/v1/investigations/{sid}", params={"event": peak}).json()
    assert d["unusualness"]["status"] == "withheld" and d["unusualness"]["reason"] == reason
    assert d["unusualness"].get("z") is None
    card = next(a for a in d["evidence"]["assessment"] if a["key"] == "unusualness")
    assert card["value"] != "Yes"


def test_discovery_rows_and_investigations_agree_on_a_sample(client):
    rows = sql(
        "SELECT series_id, strftime(start, '%Y-%m'), strftime(peak, '%Y-%m'), strftime(\"end\", '%Y-%m'), peak_z, "
        "extent, peer_n FROM CATALOG WHERE kind = 'unusual' AND NOT data_concern "
        "ORDER BY hash(series_id || CAST(peak AS VARCHAR)) LIMIT 12"
    )
    for sid, start, peak, end, z, ext, peer_n in rows:
        d = client.get(f"/api/v1/investigations/{sid}", params={"event": peak}).json()
        ep = d["episode"]
        assert ep and ep["kind"] == "unusual", sid
        assert (ep["start"][:7], ep["end"][:7]) == (start, end), sid
        assert ep["peak_z"] == pytest.approx(z, rel=1e-4), sid
        if peer_n <= 60:  # beyond 60 the investigation reads the 60 best-observed peers only
            assert d["peers"]["extent"]["class"] == ext, sid
