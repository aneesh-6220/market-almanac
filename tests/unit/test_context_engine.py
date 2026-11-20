"""The economic-context engine on synthetic sources (see ``tests/context_support.py``)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from market_almanac.context import transforms as T
from market_almanac.context.engine import economic_context
from market_almanac.context.store import ContextSnapshot
from tests import context_support as cs

EVENT, ONSET, PEAK = pd.Timestamp("2024-09-01"), pd.Timestamp("2024-06-01"), pd.Timestamp("2024-09-01")
S0, E0 = pd.Timestamp("2022-06-01"), pd.Timestamp("2025-09-01")


@pytest.fixture(scope="module")
def snap(tmp_path_factory: pytest.TempPathFactory) -> ContextSnapshot:
    return cs.build_snapshot(tmp_path_factory.mktemp("ctx"))


def local_price(growth: float = 0.005, step: float = 1.45, at: str = "2024-06") -> pd.Series:
    """A local price that jumps by ``step`` in ``at`` (about +53% over 12 months with ordinary monthly growth)."""
    p = cs.path(growth, steps={at: step})
    return pd.Series(list(p.values()), index=pd.DatetimeIndex([pd.Timestamp(f"{m}-01") for m in p]))


def run(
    snap: ContextSnapshot,
    iso3: str = "KEN",
    commodity: str = "Rice (imported)",
    currency: str | None = "KES",
    **kw: Any,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "iso3": iso3,
        "commodity_name": commodity,
        "currency": currency,
        "price": local_price(),
        "event": EVENT,
        "onset": ONSET,
        "peak": PEAK,
        "window_start": S0,
        "window_end": E0,
    } | kw
    return economic_context(snap, **args)


def test_a_large_price_rise_is_not_general_inflation(snap: ContextSnapshot) -> None:
    out = run(snap)
    price, cpi = out["price"]["yoy_pct"], out["inflation"]["headline"]["yoy_pct"]
    assert price > 0.4 and 0.04 < cpi < 0.06  # a ~50% rise beside ~5% general inflation
    rel = next(
        r for r in out["relative_changes"] if r["key"] == "price_vs_headline_cpi" and r["horizon"].startswith("12")
    )
    assert rel["status"] == "ok" and rel["relative_pct"] == pytest.approx((1 + price) / (1 + cpi) - 1)
    assert rel["relative_pct"] > 0.35  # relative to the national basket, not "inflation explains 53%"


def test_food_cpi_gives_a_second_deflator(snap: ContextSnapshot) -> None:
    out = run(snap)
    food = out["inflation"]["food"]["yoy_pct"]
    head = out["inflation"]["headline"]["yoy_pct"]
    assert food > head  # the synthetic food index rises faster and has a step
    assert out["inflation"]["food_minus_headline_yoy_pp"] == pytest.approx((food - head) * 100)
    rel = next(r for r in out["relative_changes"] if r["key"] == "price_vs_food_cpi" and r["horizon"].startswith("12"))
    assert (
        rel["deflator"] == "food CPI"
        and rel["relative_pct"]
        < next(
            r for r in out["relative_changes"] if r["key"] == "price_vs_headline_cpi" and r["horizon"].startswith("12")
        )["relative_pct"]
    )


def test_baseline_to_peak_uses_the_mean_of_the_twelve_months_before_onset(snap: ContextSnapshot) -> None:
    out = run(snap)
    p = local_price()
    base = p[(p.index >= pd.Timestamp("2023-06-01")) & (p.index <= pd.Timestamp("2024-05-01"))].mean()
    assert out["price"]["baseline_to_peak_pct"] == pytest.approx(p[PEAK] / base - 1)
    assert out["window"]["baseline_start"] == "2023-06" and out["window"]["baseline_end"] == "2024-05"


def test_missing_food_cpi_is_explicit_and_headline_still_works(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="NER", currency="XOF")
    assert out["inflation"]["food"]["state"] == "empty_series"
    assert "empty in the source" in out["inflation"]["food"]["reason"]
    assert out["inflation"]["headline"]["state"] == "ok"
    rel = next(r for r in out["relative_changes"] if r["key"] == "price_vs_food_cpi")
    assert rel["status"] == "withheld" and rel["relative_pct"] is None and "empty" in rel["reason"]
    assert any(m["key"] == "imf.cpi_food.NER" and m["state"] == "empty_series" for m in out["missing"])
    assert out["status"] == "ok"


def test_unspliced_rebase_withholds_changes_across_the_break(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="LBY", currency="LYD", event=pd.Timestamp("2025-03-01"), peak=pd.Timestamp("2025-03-01"))
    head = out["inflation"]["headline"]
    assert head["yoy_pct"] is None and "re-based in 2025-01" in head["yoy_unavailable_reason"]
    assert head["base_breaks_in_window"] == ["2025-01"]
    assert any(w["code"] == "base_break" for w in out["warnings"])
    assert head["baseline_to_peak_pct"] is None
    ix = dict(zip(out["charts"]["months"], head["chart_index"] or [], strict=False))
    assert ix.get("2024-11") is not None and ix.get("2025-03") is None  # months after the break are blanked


def test_a_series_that_ends_before_the_event_says_so(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="LBY", currency="LYD", event=pd.Timestamp("2025-09-01"), window_end=pd.Timestamp("2025-09-01"))
    head = out["inflation"]["headline"]
    assert head["coverage"]["ends_before_event"] and "ends in 2025-06" in head["yoy_unavailable_reason"]


def test_country_without_any_series_is_reported_not_guessed(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="XXX", currency="XXX", commodity="Millet")
    assert out["status"] == "no_context"
    benchmarks_only = run(snap, iso3="XXX", currency="XXX")  # world prices still exist for an unlisted country
    assert benchmarks_only["status"] == "ok" and benchmarks_only["international"]["items"][0]["local_currency"] is None
    assert {m["state"] for m in out["missing"] if m["key"].startswith("imf.")} == {"no_series"}
    assert out["exchange_rate"]["applicability"] == "no_series" and out["usd_price"] is None


def test_exchange_rate_quote_direction_and_dollar_value(snap: ContextSnapshot) -> None:
    out = run(snap)
    pa = out["exchange_rate"]["period_average"]
    assert pa["yoy_pct"] == pytest.approx(1.002**12 - 1, rel=1e-3)  # more shillings per dollar
    assert pa["usd_value_change_yoy_pct"] == pytest.approx(1 / (1 + pa["yoy_pct"]) - 1)
    assert pa["usd_value_change_yoy_pct"] < 0 and "domestic currency per US dollar" in out["exchange_rate"]["quote"]
    assert (
        abs(pa["usd_value_change_yoy_pct"]) < pa["yoy_pct"]
    )  # a +x rise in units per dollar is a smaller fall in value


def test_period_average_and_end_of_period_are_both_reported(tmp_path: Path) -> None:
    w = cs.world()
    w["fx_end_period"][0] = cs.series("KEN", cs.path(0.002, steps={"2024-08": 1.10}), ref="")
    out = run(cs.build_snapshot(tmp_path, w))
    fx = out["exchange_rate"]
    assert fx["end_period"]["yoy_pct"] > fx["period_average"]["yoy_pct"]
    assert fx["average_vs_end_period_yoy_pp"] == pytest.approx(
        (fx["end_period"]["yoy_pct"] - fx["period_average"]["yoy_pct"]) * 100
    )


def test_a_step_devaluation_is_flagged(tmp_path: Path) -> None:
    w = cs.world()
    w["fx_period_avg"][0] = cs.series("KEN", cs.path(0.002, steps={"2024-08": 1.4}), ref="")
    out = run(cs.build_snapshot(tmp_path, w))
    assert out["exchange_rate"]["period_average"]["step_changes_in_window"][0]["period"] == "2024-08"
    assert any(w["code"] == "fx_step" for w in out["warnings"])


def test_currency_union_peg_is_explained_and_verified(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="SEN", currency="XOF")
    fx = out["exchange_rate"]
    assert fx["applicability"] == "applies" and fx["currency_verified"] is True
    assert fx["regime"][0]["id"] == "xof" and fx["regime"][0]["anchor"] == "EUR"
    assert any(w["code"] == "peg" and "euro" in w["text"] for w in out["warnings"])


def test_price_currency_that_is_not_the_national_currency_is_not_converted(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="SEN", currency="NGN")
    assert out["exchange_rate"]["applicability"] == "currency_mismatch" and out["usd_price"] is None
    assert any(w["code"] == "currency_mismatch" for w in out["warnings"])
    assert (
        out["international"]["items"][0]["local_currency"] is None
    )  # no local-currency benchmark without a valid rate


def test_prices_already_in_dollars_are_not_converted_again(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="KEN", currency="USD")
    assert out["exchange_rate"]["applicability"] == "price_in_usd" and out["usd_price"] is None


def test_dollarized_economy_has_no_usable_exchange_rate(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="ECU", currency="USD")
    assert out["exchange_rate"]["applicability"] in ("price_in_usd", "dollarized")
    out = run(snap, iso3="ECU", currency="ECS")
    assert out["exchange_rate"]["applicability"] == "dollarized" and any(
        w["code"] == "dollarized" for w in out["warnings"]
    )


def test_official_rate_caution_is_attached_to_listed_countries(snap: ContextSnapshot) -> None:
    out = run(snap, iso3="ZWE", currency="ZWL")
    assert any(w["code"] == "official_rate_caution" for w in out["warnings"])
    assert out["exchange_rate"]["regime"][0]["kind"] == "official_rate_caution"


def test_unclassified_country_is_not_assumed_to_float(snap: ContextSnapshot) -> None:
    out = run(snap)
    assert out["exchange_rate"]["regime"] == [] and any(w["code"] == "regime_unclassified" for w in out["warnings"])
    assert any(w["code"] == "currency_assumed" for w in out["warnings"])


def test_usd_price_is_price_over_the_period_average_rate(snap: ContextSnapshot) -> None:
    out = run(snap)
    price_yoy, fx_yoy = out["price"]["yoy_pct"], out["exchange_rate"]["period_average"]["yoy_pct"]
    assert out["usd_price"]["yoy_pct"] == pytest.approx((1 + price_yoy) / (1 + fx_yoy) - 1)
    assert "indicative" in out["usd_price"]["note"]


def test_imported_rice_maps_to_three_benchmarks_with_medium_confidence(snap: ContextSnapshot) -> None:
    out = run(snap)["international"]
    assert out["confidence"] == "medium" and [i["benchmark_id"] for i in out["items"]] == [
        "rice_thai_5",
        "rice_viet_5",
        "rice_thai_25",
    ]
    assert any("grade" in x.lower() or "f.o.b." in x for x in out["limitations"])
    assert "never compared" in out["unit_note"]
    assert all(i["definition"]["text"] for i in out["items"])  # the benchmark's own definition travels with it


def test_benchmark_local_currency_change_decomposes_exactly(snap: ContextSnapshot) -> None:
    item = run(snap)["international"]["items"][0]
    dec = item["local_currency"]["decomposition_yoy"]
    assert dec["usd_benchmark_log"] + dec["exchange_rate_log"] == pytest.approx(dec["local_currency_log"])
    assert item["local_currency"]["yoy_pct"] == pytest.approx(dec["local_currency_change"], rel=1e-9)


def test_locally_produced_and_unmapped_commodities_get_no_benchmark(snap: ContextSnapshot) -> None:
    for name in ("Rice (local)", "Millet"):
        out = run(snap, commodity=name)
        intl = out["international"]
        assert intl["status"] == "no_benchmark" and intl["items"] == [] and intl["confidence"] == "none"
        assert any(m["state"] == "no_benchmark" for m in out["missing"])
        assert not any(p["key"].startswith("benchmark:") for p in out["lags"]["pairs"])


def test_weak_mapping_is_warned_about(snap: ContextSnapshot) -> None:
    out = run(snap, commodity="Maize")
    assert out["international"]["confidence"] == "low"
    assert any(w["code"] == "mapping_low_confidence" for w in out["warnings"])


def test_discontinued_benchmark_is_reported_as_ended(snap: ContextSnapshot) -> None:
    out = run(snap, commodity="Sorghum")
    item = out["international"]["items"][0]
    assert item["coverage"]["last_period"] == "2020-08" and item["coverage"]["ends_before_event"]
    assert "ends in 2020-08" in item["yoy_unavailable_reason"]
    assert any(w["code"] == "benchmark_ends" and "discontinued" in w["text"] for w in out["warnings"])


def test_pink_bad_cells_do_not_create_observations(tmp_path: Path) -> None:
    s = cs.build_snapshot(tmp_path, workbook={"overrides": {("maize", "2024-09"): "#VALUE!", ("maize", "2023-09"): 0}})
    item = run(s, commodity="Maize")["international"]["items"][0]
    assert item["yoy_pct"] is None and "2024-09 is missing" in item["yoy_unavailable_reason"]


def test_as_of_applies_release_lags_and_drops_the_exploratory_warning(snap: ContextSnapshot) -> None:
    now = run(snap)
    assert any(w["code"] == "vintage_exploratory" for w in now["warnings"])
    early = run(snap, as_of=pd.Timestamp("2024-09-01"))  # CPI assumed published two months later: last usable 2024-07
    head = early["inflation"]["headline"]
    assert head["coverage"]["last_period"] == "2024-07" and head["yoy_pct"] is None
    assert "ends in 2024-07" in head["yoy_unavailable_reason"] and head["coverage"]["removed_by_as_of"] > 0
    assert not any(w["code"] == "vintage_exploratory" for w in early["warnings"])
    assert early["as_of"] == "2024-09" and early["context_id"] != now["context_id"]
    fx = early["exchange_rate"]["period_average"]  # exchange rates assumed published one month later
    assert fx["coverage"]["last_period"] == "2024-08"


def test_no_look_ahead_inside_the_lag_comparison(snap: ContextSnapshot) -> None:
    out = run(snap, window_end=pd.Timestamp("2025-03-01"))
    assert out["lags"]["through"] == "2025-03"


def test_context_is_deterministic_and_json_safe(snap: ContextSnapshot) -> None:
    a, b = run(snap), run(snap)
    assert a == b and a["context_id"] == b["context_id"]
    json.dumps(a, allow_nan=False)  # no NaN or infinity leaks into the API


def test_lineage_names_the_sources_vintage_and_hashes(snap: ContextSnapshot) -> None:
    lin = {x["series_key"]: x for x in run(snap)["lineage"]}
    cpi = lin["imf.cpi_headline.KEN"]
    assert cpi["vintage_publication_date"].startswith("2026-11-19") and len(cpi["observations_sha256"]) == 64
    assert cpi["licence"] == "confirmed" and "International Monetary Fund" in cpi["attribution"]
    assert cpi["release_lag_months_assumed"] == 2 and cpi["response_sha256"]
    assert lin["wb.pink.rice_thai_5"]["provider"] == "world_bank"


# --- lagged comparison ------------------------------------------------------------------------------------------


def _lead_world(tmp_path: Path, lead: int) -> tuple[ContextSnapshot, pd.Series]:
    rng = np.random.default_rng(7)
    months = cs.months("2010-01", cs.END)
    steps = rng.normal(0, 0.04, len(months))
    bench = 300 * np.exp(np.cumsum(steps))
    over = {("rice_thai_5", m): round(float(v), 2) for m, v in zip(months, bench, strict=True)}
    snap = cs.build_snapshot(tmp_path, workbook={"overrides": over})
    ms = cs.months(cs.START, cs.END)
    idx = {m: i for i, m in enumerate(months)}
    logch = np.array([steps[idx[m] - lead] + rng.normal(0, 0.005) for m in ms])
    price = pd.Series(100 * np.exp(np.cumsum(logch)), index=pd.DatetimeIndex([pd.Timestamp(f"{m}-01") for m in ms]))
    return snap, price


def test_lag_comparison_recovers_a_known_lead(tmp_path: Path) -> None:
    snap, price = _lead_world(tmp_path, 3)
    out = run(snap, price=price, window_end=pd.Timestamp("2026-06-01"))
    pair = next(p for p in out["lags"]["pairs"] if p["key"] == "benchmark:rice_thai_5")
    assert [r["lag"] for r in pair["rows"]] == [0, 1, 2, 3, 4, 5, 6]  # all lags are returned
    best = max((r for r in pair["rows"] if r["status"] == "ok"), key=lambda r: r["spearman"])
    assert best["lag"] == 3 and best["spearman"] > 0.8
    assert "not a finding" in out["lags"]["caution"] and "p_value" not in json.dumps(out["lags"])


def test_lag_comparison_is_insufficient_with_a_short_history(snap: ContextSnapshot) -> None:
    short = local_price().loc["2024-01-01":"2025-06-01"]
    out = run(snap, price=short, window_start=pd.Timestamp("2024-01-01"))
    pair = out["lags"]["pairs"][0]
    assert (
        all(r["status"] == "insufficient" and r["spearman"] is None for r in pair["rows"])
        and not pair["any_sufficient"]
    )


# --- price gaps -------------------------------------------------------------------------------------------------


def test_missing_price_month_withholds_the_change(snap: ContextSnapshot) -> None:
    p = local_price().drop(EVENT)
    out = run(snap, price=p)
    assert out["price"]["yoy_pct"] is None and "2024-09 is missing" in out["price"]["yoy_unavailable_reason"]
    rel = [r for r in out["relative_changes"] if r["horizon"].startswith("12")]
    assert all(r["status"] == "withheld" for r in rel)


def test_transforms_are_the_ones_used(snap: ContextSnapshot) -> None:
    out = run(snap)
    ken = pd.Series(snap.series("imf.cpi_headline.KEN"))
    assert out["inflation"]["headline"]["yoy_pct"] == pytest.approx(T.yoy_pct(ken)[EVENT])
    assert math.isclose(out["inflation"]["headline"]["mom_pct"], T.mom_pct(ken)[EVENT])
