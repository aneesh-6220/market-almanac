"""The economic-context section inside a price-shock investigation, and the evidence built from it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_almanac.analytics.economic_evidence import CAUSAL_WORDS
from market_almanac.analytics.investigation import investigate
from market_almanac.context.engine import unavailable
from market_almanac.context.store import ContextSnapshot
from tests import context_support as cs
from tests.scientific.test_price_shocks import series


@pytest.fixture(scope="module")
def snap(tmp_path_factory: pytest.TempPathFactory) -> ContextSnapshot:
    return cs.build_snapshot(tmp_path_factory.mktemp("evi"))


def _price(step: float = 1.5, seed: int = 3) -> pd.Series:
    p = series(105, start="2018-01-01", seed=seed, level=100.0, noise=0.02, trend=0.003)
    p.loc["2024-06-01":] *= step
    return p


def _meta(iso3: str = "KEN", commodity: str = "Rice (imported)", currency: str = "KES") -> dict[str, Any]:
    return {
        "series_id": "s0",
        "country_iso3": iso3,
        "market_name": "Alpha",
        "commodity_name": commodity,
        "unit": "KG",
        "price_type": "Retail",
        "currency": currency,
        "first_period": "2018-01-01",
        "last_period": "2026-09-01",
        "n_observations": 105,
    }


def doc_for(
    economic: Any = None, *, meta: dict[str, Any] | None = None, prices: pd.Series | None = None, **kw: Any
) -> dict[str, Any]:
    return investigate(
        series_id="s0",
        meta=meta or _meta(),
        prices=_price() if prices is None else prices,
        snapshot_id="snap",
        raw=None,
        peers={},
        market_series={},
        macro=None,
        environment=None,
        economic=economic,
        event="2024-09",
        country_name="Testland",
        **kw,
    )


def _mech(doc: dict[str, Any], key: str) -> dict[str, Any]:
    return next(m for m in doc["evidence"]["mechanisms"] if m["key"] == key)


def test_existing_investigations_are_unchanged_without_economic_context() -> None:
    d = doc_for(None)
    assert "economic" not in d["context"] and "economic" not in d["evidence"]
    assert (
        _mech(d, "macro")["status"] == "cannot_be_assessed"
        and _mech(d, "international")["status"] == "cannot_be_assessed"
    )
    assert "source" not in _mech(d, "macro")


def test_configuration_identity_does_not_depend_on_the_context(snap: ContextSnapshot) -> None:
    a, b = doc_for(None), doc_for(snap)
    assert a["config"] == b["config"] and a["config_id"] == b["config_id"]  # links and exports keep working
    assert (
        b["context"]["economic"]["context_id"]
        and b["context"]["economic"]["snapshot"]["snapshot_id"] == snap.snapshot_id
    )
    for k in ("magnitude", "unusualness", "peers", "breadth", "persistence", "seasonality", "signals"):
        assert a[k] == b[k]  # every v1.3 result is untouched


def test_a_large_rise_beside_small_inflation_is_reported_as_such(snap: ContextSnapshot) -> None:
    d = doc_for(snap)
    eco = d["evidence"]["economic"]
    text = " ".join(x["text"] for x in eco["quantitative"])
    assert "+5" in text and "consumer price index changed +4" in text  # roughly 55% against roughly 5%
    macro = _mech(d, "macro")
    # headline CPI argues against; the faster-rising food index is partly consistent: the mechanism takes the latter
    assert macro["status"] == "partly_consistent" and macro["source"] == "economic_context"
    props = {p["proposition"]: p for p in eco["propositions"]}
    general = next(p for k, p in props.items() if k.startswith("General inflation"))
    assert general["status"] == "less_likely" and "does not exclude a local" in general["basis"]


def test_the_international_mechanism_is_assessed_only_with_a_mapped_benchmark(snap: ContextSnapshot) -> None:
    d = doc_for(snap)
    assert _mech(d, "international")["status"] in ("less_likely", "partly_consistent", "consistent")
    millet = doc_for(snap, meta=_meta(commodity="Millet"))
    assert _mech(millet, "international")["status"] == "cannot_be_assessed"
    assert any("No international benchmark" in x["text"] for x in millet["evidence"]["economic"]["observed"])
    maize = doc_for(snap, meta=_meta(commodity="Maize"))
    assert _mech(maize, "international")["status"] == "context_only"  # low-confidence mapping: neither for nor against


def test_a_price_that_tracks_the_cpi_is_consistent_with_general_inflation(tmp_path: Path) -> None:
    w = cs.world()
    w["cpi_headline"][0] = cs.series("KEN", cs.path(0.034))  # ~49% a year of general inflation
    snap = cs.build_snapshot(tmp_path, w)
    tracking = series(105, start="2018-01-01", seed=3, level=100.0, noise=0.02, trend=0.034)
    up = doc_for(snap, prices=tracking)
    assert 0.3 < up["magnitude"]["event_yoy_pct"] < 0.8
    eco = up["evidence"]["economic"]
    general = next(p for p in eco["propositions"] if p["proposition"].startswith("General inflation"))
    assert general["status"] in ("consistent", "partly_consistent")
    assert eco["consistent"] and all(c["inference"] == "associational" for c in eco["consistent"])


def test_no_causal_verbs_outside_the_disclaimers(snap: ContextSnapshot) -> None:
    d = doc_for(snap)
    eco = d["evidence"]["economic"]
    for layer in ("observed", "quantitative", "consistent", "unresolved"):
        for st in eco[layer]:
            assert not any(w in st["text"].lower() for w in CAUSAL_WORDS), st["text"]
    for p in eco["propositions"]:
        assert not any(w in p["basis"].lower() for w in CAUSAL_WORDS), p["basis"]
    for m in d["evidence"]["mechanisms"]:
        if m.get("source") == "economic_context":
            assert not any(w in " ".join(m["evidence"]).lower() for w in CAUSAL_WORDS)
    assert eco["causal"] and all(c["inference"] == "causal" for c in eco["causal"])  # named only to be disclaimed


def test_missing_food_cpi_appears_as_a_gap_and_a_withheld_proposition(snap: ContextSnapshot) -> None:
    d = doc_for(snap, meta=_meta(iso3="NER", currency="XOF"))
    eco = d["evidence"]["economic"]
    assert any("imf.cpi_food.NER" in g or "food" in g.lower() for g in eco["gaps"])
    food = next(p for p in eco["propositions"] if p["proposition"].startswith("Food inflation"))
    assert food["status"] == "cannot_be_assessed" and "empty" in food["basis"]


def test_peg_and_mismatch_shape_the_fx_proposition(snap: ContextSnapshot) -> None:
    peg = doc_for(snap, meta=_meta(iso3="SEN", currency="XOF"))
    fx = next(p for p in peg["evidence"]["economic"]["propositions"] if p["proposition"].startswith("A depreciation"))
    assert "pegged" in fx["basis"] or fx["status"] == "cannot_be_assessed"
    bad = doc_for(snap, meta=_meta(iso3="SEN", currency="NGN"))
    fx = next(p for p in bad["evidence"]["economic"]["propositions"] if p["proposition"].startswith("A depreciation"))
    assert fx["status"] == "cannot_be_assessed" and "differs" in fx["basis"]


def test_a_country_without_context_keeps_the_v13_wording(snap: ContextSnapshot) -> None:
    d = doc_for(snap, meta=_meta(iso3="XXX", commodity="Millet", currency="XXX"))
    assert d["context"]["economic"]["status"] == "no_context" and "economic" not in d["evidence"]
    assert any("absent or unlikely" in u["text"] for u in d["evidence"]["unsupported"])


def test_a_supplied_unavailable_section_passes_through(snap: ContextSnapshot) -> None:
    sec = unavailable("the economic-context artefact is not installed on this deployment", "not_installed")
    d = doc_for(sec)
    assert d["context"]["economic"]["status"] == "not_installed" and "economic" not in d["evidence"]


def test_investigation_with_context_is_deterministic_and_json_safe(snap: ContextSnapshot) -> None:
    a, b = doc_for(snap), doc_for(snap)
    assert a == b
    json.dumps(a, allow_nan=False)


def test_as_of_changes_the_context_but_not_the_investigation_identity(snap: ContextSnapshot) -> None:
    now, early = doc_for(snap), doc_for(snap, as_of="2024-09")
    assert (
        now["config_id"] == early["config_id"]
        and now["context"]["economic"]["context_id"] != early["context"]["economic"]["context_id"]
    )
    assert (
        early["context"]["economic"]["inflation"]["headline"]["yoy_pct"] is None
    )  # not yet published at the as-of month


def test_a_partly_consistent_proposition_is_not_described_as_accounting_for_most(snap: ContextSnapshot) -> None:
    eco = doc_for(snap)["evidence"]["economic"]
    partly = [p for p in eco["propositions"] if p["status"] == "partly_consistent"]
    assert partly
    texts = [c["text"] for c in eco["consistent"]]
    for p in partly:
        line = next(t for t in texts if p["proposition"].lower() in t)
        assert "only partly consistent" in line and "not most of it" in line


def test_the_international_status_uses_the_median_benchmark_not_the_most_favourable(snap: ContextSnapshot) -> None:
    d = doc_for(snap)
    prop = next(p for p in d["evidence"]["economic"]["propositions"] if p["proposition"].startswith("International"))
    if prop["status"] != "cannot_be_assessed":
        assert "at the median across" in prop["basis"] and "range" in prop["basis"]


def test_the_economic_section_conforms_to_the_published_schema(snap: ContextSnapshot) -> None:
    from tests.schema_check import validate

    schema = json.loads((Path(__file__).parents[2] / "docs/schemas/economic-context-1.schema.json").read_text())
    cases = [
        doc_for(snap),
        doc_for(snap, meta=_meta(iso3="NER", currency="XOF")),  # an empty food index
        doc_for(snap, meta=_meta(iso3="SEN", currency="XOF")),  # a peg
        doc_for(snap, meta=_meta(iso3="ECU", currency="USD")),  # dollarized
        doc_for(snap, meta=_meta(iso3="XXX", commodity="Millet", currency="XXX")),  # no context
        doc_for(unavailable("not installed here", "not_installed")),
    ]
    for d in cases:
        assert validate(d["context"]["economic"], schema) == [], d["context"]["economic"]["status"]
    bad = json.loads(json.dumps(cases[0]["context"]["economic"]))
    del bad["lineage"]
    bad["window"]["event"] = "2024-6"
    errs = validate(bad, schema)
    assert errs  # the checker is not vacuous


def test_a_frozen_official_rate_is_described_as_not_moving_and_never_as_fewer_units(tmp_path: Path) -> None:
    w = cs.world()
    for conc in ("fx_period_avg", "fx_end_period"):
        w[conc][0] = cs.series("KEN", cs.path(0.0, start=100.0), ref="")  # an administered rate that never moved
    d = doc_for(cs.build_snapshot(tmp_path, w))
    quant = [x["text"] for x in d["evidence"]["economic"]["quantitative"]]
    text = " ".join(quant)
    assert "fewer units per dollar" not in text and "the official rate did not move" in text
    assert any("take too few distinct values" in t for t in quant)


def test_the_dollar_price_of_a_country_with_divergent_official_rates_carries_the_caution(
    snap: ContextSnapshot,
) -> None:
    d = doc_for(snap, meta=_meta(iso3="ZWE", currency="ZWG"))
    eco = d["context"]["economic"]
    warn = next(w for w in eco["warnings"] if w["code"] == "official_rate_caution")
    assert warn["text"].startswith("ZWE is listed")
    text = " ".join(x["text"] for x in d["evidence"]["economic"]["quantitative"])
    assert "in US dollars changed" in text and "may be far from the dollar price households faced" in text
