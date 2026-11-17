"""Descriptive analytics: summaries, unusual movements, comparisons and briefs (hand-checked numbers)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shocktrace.analytics.brief import build_brief
from shocktrace.analytics.compare import align, assess_comparability, compare, index_series
from shocktrace.analytics.movement import (
    MIN_HISTORY,
    assess_movement,
    label_for,
    log_changes,
    movement_history,
    peer_context,
)
from shocktrace.analytics.summary import monthly_records, seasonal_profile, series_summary


def _series(n: int = 72, seed: int = 0, sd: float = 0.03, start: str = "2019-01-01") -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="MS")
    return pd.Series(500 * np.exp(np.cumsum(rng.normal(0, sd, n))), index=idx)


# --- movement ---------------------------------------------------------------------------------


def test_percentile_and_robust_z_by_hand():
    # 30 alternating +/-1% changes, then one +10% change
    steps = [0.01, -0.01] * 15 + [0.10]
    p = pd.Series(100 * np.exp(np.cumsum([0.0, *steps])), index=pd.date_range("2020-01-01", periods=32, freq="MS"))
    m = assess_movement(p)
    assert m["span_months"] == 1 and m["direction"] == "up"
    assert m["log_change"] == pytest.approx(0.10) and m["pct_change"] == pytest.approx(np.exp(0.10) - 1)
    assert m["overall"]["n_reference"] == 30
    assert m["overall"]["percentile_of_size"] == 1.0  # larger in size than all 30 earlier changes
    # median of the reference is 0; MAD is 0.01 -> scale 1.4826*0.01
    assert m["overall"]["robust_z"] == pytest.approx(0.10 / (1.4826 * 0.01))
    assert m["label"] == "exceptional" and m["stable"] is False
    assert any("unstable" in w for w in m["warnings"])


def test_labels_and_history_threshold():
    assert label_for(0.5, 60) == "typical" and label_for(0.85, 60) == "larger_than_usual"
    assert label_for(0.96, 60) == "unusual" and label_for(0.995, 60) == "exceptional"
    assert label_for(0.999, MIN_HISTORY - 1) == "insufficient_history"
    short = _series(10)
    m = assess_movement(short)
    assert m["label"] == "insufficient_history" and any("at least" in w for w in m["warnings"])
    assert assess_movement(short.iloc[:1])["status"] == "insufficient_history"


def test_assessment_uses_only_earlier_changes():
    p = _series(80)
    at = pd.Timestamp("2023-06-01")
    a = assess_movement(p, at)
    q = p.copy()
    q[q.index > at] *= 50  # anything after the assessed month is irrelevant
    b = assess_movement(q, at)
    assert a == b and a["period"] == "2023-06-01"


def test_change_across_missing_months_is_compared_with_same_span_changes():
    p = _series(80)
    t = p.index[-1]
    gap = p.drop([t - pd.DateOffset(months=1), t - pd.DateOffset(months=2)])
    m = assess_movement(gap)
    assert m["span_months"] == 3 and m["spans_gap"] is True
    assert m["reference_period"] == (t - pd.DateOffset(months=3)).date().isoformat()
    assert m["log_change"] == pytest.approx(np.log(p[t] / p[t - pd.DateOffset(months=3)]))
    ref = log_changes(gap, 3)
    assert m["overall"]["n_reference"] == int(ref[ref.index < t].notna().sum())
    assert any("spans 3 months" in w for w in m["warnings"])
    far = p.drop(p.index[-9:-1])
    assert assess_movement(far)["status"] == "gap_too_long"


def test_seasonal_reference_uses_same_calendar_month():
    p = _series(96)
    m = assess_movement(p)
    t = p.index[-1]
    d = log_changes(p, 1)
    same = d[(d.index < t) & (d.index.month == t.month)].dropna()
    assert m["seasonal"]["n_reference"] == len(same) == 7 and m["seasonal"]["calendar_month"] == t.month
    assert m["year_on_year"]["log_change"] == pytest.approx(np.log(p.iloc[-1] / p.iloc[-13]))


def test_movement_history_flags_a_planted_jump_and_is_point_in_time():
    p = _series(90, sd=0.02)
    jump = p.index[60]
    p[p.index >= jump] *= 1.35
    hist = movement_history(p)
    assert jump.date().isoformat() in {h["period"] for h in hist}
    assert all(h["n_reference"] >= MIN_HISTORY for h in hist)
    earlier = {h["period"] for h in hist if h["period"] < "2023-06-01"}
    trunc = {h["period"] for h in movement_history(p[p.index < "2023-06-01"])}
    assert earlier == trunc  # a past month's flag does not change when later data arrive


def test_peer_context_distinguishes_shared_from_isolated_reversing_moves():
    idx = pd.date_range("2022-01-01", periods=6, freq="MS")
    base = pd.DataFrame({f"m{i}": 100.0 for i in range(6)}, index=idx)
    shared = base.copy()
    shared.loc[idx[3] :] *= 1.2  # every market rises 20% in April and stays there
    out = peer_context(shared, "m0", idx[3])
    assert out["pattern"] == "shared" and out["share_same_direction"] == 1.0 and out["n_peers"] == 5
    assert out["peer_median_pct_change"] == pytest.approx(0.2)
    lone = base.copy()
    lone.loc[idx[3], "m0"] = 150.0  # one market jumps and returns next month
    out = peer_context(lone, "m0", idx[3])
    assert out["pattern"] == "isolated_reversing" and out["reverses_next_month"] is True
    assert peer_context(base[["m0", "m1"]], "m0", idx[3])["status"] == "too_few_peers"
    assert peer_context(base, "zz", idx[3]) is None


# --- summary ----------------------------------------------------------------------------------


def test_series_summary_reports_observation_month_and_changes():
    idx = pd.date_range("2024-01-01", periods=14, freq="MS")
    p = pd.Series([100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 125, 150.0], index=idx)
    p = p.drop(idx[5])  # June 2024 missing
    s = series_summary(p, dataset_last_period=pd.Timestamp("2025-05-01"))
    assert s["latest_period"] == "2025-02-01" and s["latest_price"] == 150.0
    assert s["changes"]["m1"]["pct_change"] == pytest.approx(150 / 125 - 1)
    assert s["changes"]["m12"]["reference_period"] == "2024-02-01"
    assert s["changes"]["m12"]["pct_change"] == pytest.approx(150 / 102 - 1)
    assert s["n_observations"] == 13 and s["months_spanned"] == 14 and s["coverage"] == pytest.approx(13 / 14)
    assert s["missing_months_last_24"] == 1  # June 2024; months before the series began are not counted
    assert s["months_behind_dataset"] == 3
    assert s["range_12m"]["max"] == 150.0 and s["range_12m"]["n"] == 11  # Mar 2024..Feb 2025 minus June
    assert series_summary(pd.Series(dtype=float))["status"] == "no_valid_prices"
    recs = monthly_records(p)
    assert len(recs) == 14 and recs[5] == {"period": "2024-06-01", "price": None}


def test_seasonal_profile_recovers_a_planted_pattern_despite_a_trend():
    idx = pd.date_range("2017-01-01", periods=96, freq="MS")
    seasonal = 1 + 0.2 * np.sin(2 * np.pi * (idx.month - 5) / 12)  # peaks in August, trough in February
    trend = np.exp(0.01 * np.arange(96))
    prof = seasonal_profile(pd.Series(300 * seasonal * trend, index=idx))
    assert prof["status"] == "ok" and prof["years_used"] == 8
    assert prof["peak_month"] == 8 and prof["trough_month"] == 2
    assert prof["seasonal_amplitude"] == pytest.approx(1.2 / 0.8 - 1, abs=0.12)
    assert len(prof["months"]) == 12 and all(m["n_years"] == 8 for m in prof["months"])
    assert seasonal_profile(pd.Series(300.0, index=idx[:20]))["status"] == "insufficient_history"


# --- comparison -------------------------------------------------------------------------------


def _meta(**kw):  # type: ignore[no-untyped-def]
    base = {
        "commodity_name": "Millet",
        "price_type": "Retail",
        "unit": "KG",
        "currency": "XOF",
        "country_iso3": "BFA",
        "price_flag": "actual",
    }
    return {**base, **kw}


def test_comparability_rules():
    assert assess_comparability([_meta(), _meta()])["level"] == "absolute_and_indexed"
    other_unit = assess_comparability([_meta(), _meta(unit="100 KG")])
    assert other_unit["level"] == "invalid" and "unit differs" in other_unit["reasons"][0]
    assert assess_comparability([_meta(), _meta(commodity_name="Sorghum")])["level"] == "invalid"
    assert assess_comparability([_meta(), _meta(price_type="Wholesale")])["level"] == "invalid"
    fx = assess_comparability([_meta(), _meta(currency="NGN", country_iso3="NGA")])
    assert fx["level"] == "indexed_only" and fx["absolute"] is False
    assert any("no conversion" in r for r in fx["reasons"]) and any("different countries" in r for r in fx["reasons"])
    same_cur = assess_comparability([_meta(), _meta(country_iso3="MLI")])  # both XOF
    assert same_cur["absolute"] and any("cost-of-living" in r for r in same_cur["reasons"])
    assert assess_comparability([_meta()])["level"] == "single"
    assert assess_comparability([_meta()] * 9)["level"] == "invalid"


def test_alignment_and_indexing_by_hand():
    a = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2024-01-01", periods=3, freq="MS"))
    b = pd.Series([200.0, 250.0], index=pd.date_range("2024-02-01", periods=2, freq="MS"))
    f = align({"a": a, "b": b})
    assert list(f.index.strftime("%Y-%m")) == ["2024-01", "2024-02", "2024-03"] and np.isnan(f.loc["2024-01-01", "b"])
    idx, base = index_series(f)
    assert base == {"mode": "common_base", "base_period": "2024-02-01"}  # first month both are observed
    assert idx.loc["2024-03-01", "a"] == pytest.approx(110.0) and idx.loc["2024-03-01", "b"] == pytest.approx(125.0)
    assert idx.loc["2024-01-01", "a"] == pytest.approx(100 / 110 * 100)
    c = pd.Series([5.0], index=[pd.Timestamp("2023-01-01")])
    _, base2 = index_series(align({"a": a, "c": c}))
    assert base2["mode"] == "own_first_observation" and "warning" in base2


def test_compare_returns_spread_missingness_and_refuses_incompatible_series():
    a, b = _series(40, 1), _series(40, 2) * 1.5
    b = b.drop(b.index[10:14])
    out = compare({"a": a, "b": b}, [_meta(), _meta()])
    assert out["status"] == "ok" and out["window"]["months"] == 40 and out["months_all_observed"] == 36
    sb = next(s for s in out["series"] if s["series_id"] == "b")
    assert sb["missing_share"] == pytest.approx(4 / 40) and sb["n_observations"] == 36
    sp = out["latest_common_spread"]
    assert sp["max_over_min"] == pytest.approx(max(a.iloc[-1], b.iloc[-1]) / min(a.iloc[-1], b.iloc[-1]))
    assert out["pairs"][0]["n"] == 34 and out["pairs"][0]["correlation_of_monthly_changes"] is not None
    assert out["rows"][10]["prices"]["b"] is None  # missing stays missing
    bad = compare({"a": a, "b": b}, [_meta(), _meta(unit="100 KG")])
    assert bad["status"] == "not_comparable" and bad["rows"] == []
    fx = compare({"a": a, "b": b}, [_meta(), _meta(currency="NGN", country_iso3="NGA")])
    assert fx["status"] == "ok" and fx["latest_common_spread"] is None  # no level comparison across currencies
    win = compare(
        {"a": a, "b": b}, [_meta(), _meta()], start=pd.Timestamp("2021-01-01"), end=pd.Timestamp("2021-12-01")
    )
    assert win["window"] == {"start": "2021-01-01", "end": "2021-12-01", "months": 12}


# --- brief ------------------------------------------------------------------------------------


META = {
    "commodity_name": "Millet",
    "market_name": "Sankaryare",
    "country_iso3": "BFA",
    "price_type": "Retail",
    "unit": "KG",
    "currency": "XOF",
}


def test_brief_sentences_are_traceable_to_evidence_and_make_no_causal_claim():
    p = _series(80, 3)
    p.iloc[-1] = p.iloc[-2] * 1.3
    summ, mov = series_summary(p, p.index[-1]), assess_movement(p)
    brief = build_brief(
        META,
        summ,
        mov,
        quality={"eligible": True},
        peers={
            "status": "ok",
            "n_peers": 40,
            "share_same_direction": 0.9,
            "peer_median_pct_change": 0.12,
            "pattern": "shared",
        },
        environment={
            "status": "ok",
            "market_cell": {"period": "2025-07-01", "rain_anomaly_z": -1.4, "qc_flagged": False},
            "production_region": {
                "crop": "millet",
                "period": "2025-07-01",
                "season_rain_anomaly_z": -0.2,
                "in_season": True,
            },
        },
        forecast={
            "status": "issued",
            "target_period": "2025-09-01",
            "validation_status": "validated_no_better_than_baseline",
        },
    )
    text = brief["text"]
    assert f"{summ['latest_price']:,.0f} XOF per KG" in text and "rose 30.0% from the previous month" in text
    assert "among the largest movements" in text and "90% of the 40 other markets" in text
    assert "below the average of earlier years" in text and "close to that of earlier seasons" in text
    assert "no demonstrated skill" in text and "assumed data-availability scenario" in text
    sections = [s["section"] for s in brief["sentences"]]
    for needed in ("latest", "what_changed", "unusualness", "data", "environment", "forecast", "uncertainty"):
        assert needed in sections
    lowered = text.lower()
    for banned in ("because", "due to", "caused", "driven by", "as a result of", "crisis", "shortage"):
        assert banned not in lowered
    assert brief["evidence"]["movement"] is mov and brief["evidence"]["summary"] is summ


def test_brief_states_what_is_missing_instead_of_guessing():
    p = _series(12, 4)
    brief = build_brief(
        META,
        series_summary(p),
        assess_movement(p),
        quality={"eligible": False, "reasons": ["only 12 valid monthly prices (< 48)"]},
    )
    t = brief["text"]
    assert "not enough history" in t and "does not meet the completeness rules" in t and "only 12 valid" in t
    assert "No weather context is stored" in t and "no forecast is shown" in t
    withheld = build_brief(
        META, series_summary(p), assess_movement(p), forecast={"status": "withheld", "reason": "only 9 test periods"}
    )
    assert "No forecast is shown for this series: only 9 test periods." in withheld["text"]
    empty = build_brief(META, series_summary(pd.Series(dtype=float)), {"status": "insufficient_history"})
    assert "no valid price observations" in empty["text"]


def test_brief_describes_an_unchanged_price_without_percentile_wording():
    p = _series(80, 3)
    p.iloc[-1] = p.iloc[-2]
    mov = assess_movement(p)
    assert mov["direction"] == "flat"
    text = build_brief(META, series_summary(p, p.index[-1]), mov)["text"]
    assert "The price did not change" in text and "larger than 0%" not in text
