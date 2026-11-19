"""Scientific correctness of price-shock detection, episodes, comparisons and evidence (synthetic, offline)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from market_almanac.analytics.shocks import (
    MIN_REFERENCE,
    Z_ELEVATED,
    clean_monthly,
    compute_signals,
    episode_at,
    extent,
    find_episodes,
    seasonal_expectation,
    state_near,
)


def series(
    n: int = 120,
    start: str = "2012-01-01",
    seed: int = 0,
    level: float = 100.0,
    noise: float = 0.03,
    seasonal: float = 0.0,
    trend: float = 0.0,
) -> pd.Series:
    """Log-random-walk-free monthly prices: level x exp(trend t + seasonal sin + iid noise)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="MS")
    t = np.arange(n)
    lp = (
        np.log(level)
        + trend * t
        + seasonal * np.sin(2 * np.pi * (idx.month.to_numpy() - 1) / 12)
        + rng.normal(0, noise, n)
    )
    return pd.Series(np.exp(lp), index=idx)


def shock(p: pd.Series, at: str, months: int, factor: float) -> pd.Series:
    q = p.copy()
    i = q.index.get_loc(pd.Timestamp(at))
    q.iloc[i : i + months] *= factor
    return q


# --- signals --------------------------------------------------------------------------------------------


def test_no_assessment_on_sparse_or_short_series():
    sig = compute_signals(series(30))
    assert set(sig["status"]) <= {"none", "withheld"}
    assert set(sig.loc[sig["status"] == "withheld", "reason"]) == {"short_history"}
    assert sig["z"].isna().all()
    # a long series with most recent months missing: withheld as sparse, not scored
    p = series(120)
    recent = p.index[-24:-1]
    sparse = p.drop([t for i, t in enumerate(recent) if i % 3])  # two of every three recent months missing
    s2 = compute_signals(sparse)
    last = s2[s2["r12"].notna()].iloc[-1]
    assert last["status"] == "withheld" and last["reason"] == "sparse_recent"


def test_missing_months_are_not_zero_changes_and_never_bridged():
    p = series(100).drop(pd.Timestamp("2016-06-01"))
    sig = compute_signals(p)
    assert not sig.at[pd.Timestamp("2016-06-01"), "observed"]
    assert np.isnan(sig.at[pd.Timestamp("2016-06-01"), "r1"]) and np.isnan(sig.at[pd.Timestamp("2016-07-01"), "r1"])
    assert np.isnan(sig.at[pd.Timestamp("2017-06-01"), "r12"])  # its comparison month is missing


def test_zero_negative_and_invalid_prices_are_dropped_before_any_ratio():
    p = series(80)
    p.iloc[40] = 0.0
    p.iloc[41] = -5.0
    p.iloc[42] = np.nan
    p.iloc[43] = np.inf
    c = clean_monthly(p)
    assert len(c) == 76 and (c > 0).all() and np.isfinite(c).all()
    sig = compute_signals(p)
    assert np.isfinite(sig["r12"].dropna()).all()
    assert not sig["observed"].iloc[40:44].any()


def test_duplicate_month_keeps_first_and_index_is_monthly():
    p = series(40)
    dup = pd.concat([p, pd.Series([999.0], index=[p.index[10] + pd.Timedelta(days=14)])])
    c = clean_monthly(dup)
    assert c.index.is_unique and c.loc[p.index[10]] == pytest.approx(p.iloc[10])


def test_no_leakage_future_data_cannot_change_a_past_assessment():
    p = series(150, seed=3)
    base = compute_signals(p.iloc[:110])
    full = compute_signals(shock(p, p.index[120].isoformat(), 20, 3.0))
    t = p.index[105]
    for c in ("z", "percentile", "n_reference"):
        assert base.at[t, c] == pytest.approx(full.at[t, c], nan_ok=True)


def test_degenerate_constant_history_is_withheld_not_scored():
    idx = pd.date_range("2010-01-01", periods=96, freq="MS")
    p = pd.Series(100.0, index=idx)
    p.iloc[-1] = 400.0  # a x4 jump after years of carried-forward prices
    sig = compute_signals(p)
    assert sig.iloc[-1]["status"] == "withheld" and sig.iloc[-1]["reason"] == "degenerate_history"
    assert not [e for e in find_episodes(sig) if e["kind"] == "unusual"]
    assert [e for e in find_episodes(sig) if e["kind"] == "withheld"]


def test_eligibility_needs_enough_years_and_reference_changes():
    sig = compute_signals(series(12 + MIN_REFERENCE + 24))
    ok = sig[sig["status"] == "ok"]
    assert len(ok) >= 1 and (ok["n_reference"] >= MIN_REFERENCE).all() and (ok["reference_years"] >= 4).all()


# --- episodes -------------------------------------------------------------------------------------------


def test_a_genuine_sustained_shock_is_one_persistent_unusual_episode():
    p = shock(series(132, seed=1), "2019-03-01", 9, 1.6)
    eps = [e for e in find_episodes(compute_signals(p)) if e["kind"] == "unusual" and e["direction"] == "up"]
    around = [e for e in eps if "2018-09-01" <= e["start"] <= "2019-12-01"]
    assert len(around) == 1  # one episode, not fragments (earlier single noisy months may also qualify)
    e = around[0]
    assert e["start"] == "2019-03-01" and e["duration_months"] >= 8
    assert e["peak_z"] >= Z_ELEVATED and e["peak_percentile"] == 1.0
    assert e["peak_yoy_pct"] == pytest.approx(0.6, abs=0.15)
    assert not e["data_concern"] and e["peak_index"] > 140
    assert e["baseline"]["n"] == 12


def test_a_corrupted_single_month_spike_is_flagged_as_a_data_concern():
    p = series(132, seed=2)
    p.iloc[90] *= 10  # x10 for one month (unit or keying error), then back
    eps = find_episodes(compute_signals(p))
    up = [e for e in eps if e["kind"] == "unusual" and e["direction"] == "up"]
    assert len(up) == 1 and up[0]["duration_months"] == 1
    assert {"implausible_jump", "single_month_reversed"} <= set(up[0]["flags"]) and up[0]["data_concern"]
    # twelve months later the spike becomes the comparison month: a mirrored fall flagged as a base effect
    down = [e for e in eps if e["direction"] == "down" and e["kind"] == "unusual"]
    assert down and "possible_base_effect" in down[0]["flags"]


def test_regular_seasonality_alone_is_not_unusual():
    p = series(144, seed=4, seasonal=0.25, noise=0.02)
    eps = [e for e in find_episodes(compute_signals(p)) if e["kind"] == "unusual"]
    assert not eps  # +/-25% seasonal swings every year: 12-month changes stay ordinary


def test_seasonal_expectation_separates_a_seasonal_rise_from_a_shock():
    p = series(144, seed=5, seasonal=0.25, noise=0.01)
    sig = compute_signals(p)
    # a rise from the trough (Oct) to the peak (Apr) is what the pattern predicts
    se = seasonal_expectation(sig, pd.Timestamp("2021-01-01"), pd.Timestamp("2021-04-01"))
    assert se["status"] == "ok" and se["verdict"] == "largely_seasonal"
    shocked = shock(p, "2021-01-01", 4, 1.8)
    se2 = seasonal_expectation(compute_signals(shocked), pd.Timestamp("2021-01-01"), pd.Timestamp("2021-04-01"))
    assert (
        se2["verdict"] in ("partly_seasonal", "not_seasonal") and se2["observed_change_pct"] > se["observed_change_pct"]
    )


def test_large_nominal_change_typical_under_inflation_is_not_unusual():
    p = series(132, seed=6, trend=np.log(1.04), noise=0.02)  # ~60% a year, every year
    eps = find_episodes(compute_signals(p))
    assert not [e for e in eps if e["kind"] == "unusual" and e["direction"] == "up"]
    typical = [e for e in eps if e["kind"] == "large_typical" and e["direction"] == "up"]
    assert typical and typical[0]["peak_yoy_pct"] > 0.25


def test_episode_lookup_prefers_unusual():
    p = shock(series(132, seed=1), "2019-03-01", 9, 1.6)
    eps = find_episodes(compute_signals(p))
    assert episode_at(eps, pd.Timestamp("2019-06-01"))["kind"] == "unusual"
    assert episode_at(eps, pd.Timestamp("2014-01-01")) is None


# --- extent ---------------------------------------------------------------------------------------------


def _panel(n_peers: int, shocked: int, seed: int = 10) -> dict[str, pd.Series]:
    out = {}
    for i in range(n_peers):
        p = series(132, seed=seed + i)
        out[f"s{i}"] = shock(p, "2019-03-01", 6, 1.7) if i < shocked else p
    return out


@pytest.mark.parametrize(("shocked", "expected"), [(9, "widespread"), (1, "local"), (4, "mixed")])
def test_local_versus_widespread(shocked, expected):
    panel = _panel(10, shocked)
    sigs = {k: compute_signals(v) for k, v in panel.items()}
    peak = pd.Timestamp("2019-05-01")
    states = [state_near(s, peak, "up") for k, s in sigs.items() if k != "s0"]
    assert extent(states)["class"] == expected


def test_extent_is_inconclusive_with_too_few_assessable_peers():
    panel = _panel(3, 3)
    sigs = {k: compute_signals(v.iloc[-40:]) for k, v in panel.items()}  # too short to assess
    states = [state_near(s, pd.Timestamp("2019-05-01"), "up") for s in sigs.values()]
    ex = extent(states)
    assert ex["class"] == "inconclusive" and ex["n_assessable"] == 0


def test_extreme_z_scores_are_not_reported_with_false_precision():
    from market_almanac.analytics.evidence import ztext

    assert ztext(3.24) == "+3.2" and ztext(-2.05) == "-2.0"
    assert ztext(145.7) == "beyond +10" and ztext(-12.0) == "beyond -10"


def test_rank_wording():
    from market_almanac.analytics.evidence import rank_text

    assert rank_text(1.0, 71, True) == "higher than all 71"
    assert rank_text(0.93, 71, True) == "higher than 93% of the 71"
    assert rank_text(1.0, 40, False) == "lower than all 40"


def _meta(sid: str, commodity: str) -> dict:
    return {
        "series_id": sid,
        "country_iso3": "TST",
        "market_name": "Alpha",
        "commodity_name": commodity,
        "unit": "KG",
        "price_type": "Retail",
        "currency": "TSH",
        "first_period": "2012-01-01",
        "last_period": "2022-12-01",
        "n_observations": 132,
    }


def _doc_with_foods(others: dict, **kw):  # type: ignore[no-untyped-def]
    from market_almanac.analytics.investigation import investigate

    own = shock(series(132, seed=1), "2019-03-01", 9, 1.6)
    return investigate(
        series_id="s0",
        meta=_meta("s0", "Rice (imported)"),
        prices=own,
        snapshot_id="snap",
        raw=None,
        peers=kw.pop("peers", {}),
        market_series=others,
        macro=None,
        environment=None,
        event="2019-08",
        country_name="Testland",
        **kw,
    )


def _macro(doc: dict) -> dict:
    return next(m for m in doc["evidence"]["mechanisms"] if m["key"] == "macro")


def _group(m: dict, key: str) -> list[str]:
    return next(g["items"] for g in m["evidence_groups"] if g["key"] == key)


def test_without_price_index_data_calm_local_foods_do_not_argue_against_inflation():
    others = {f"f{i}": (_meta(f"f{i}", f"Food {i}"), series(132, seed=40 + i)) for i in range(5)}
    doc = _doc_with_foods(others)
    assert doc["breadth"]["extent"]["class"] == "narrow" and doc["context"]["macro"]["cpi"] is None
    macro = _macro(doc)
    # not "not indicated" / "less likely": with no CPI or exchange rate the mechanism cannot be tested either way
    assert macro["status"] == "cannot_be_assessed"
    assert any("no consumer price index" in e for e in macro["evidence"])
    assert "higher than all" in doc["evidence"]["conclusion"]["text"]
    assert any("absent or unlikely" in x["text"] for x in doc["evidence"]["unsupported"])


def test_macro_evidence_keeps_nominal_increases_unusualness_mechanism_evidence_and_gaps_apart():
    # five foods that rise ~34% every year: large in nominal terms, ordinary for each of them
    others = {f"f{i}": (_meta(f"f{i}", f"Food {i}"), series(132, seed=40 + i, trend=0.025)) for i in range(5)}
    doc = _doc_with_foods(others)
    macro = _macro(doc)
    assert [g["key"] for g in macro["evidence_groups"]] == ["nominal", "unusual", "mechanism", "missing"]
    nominal, unusual_, mech, missing = (_group(macro, k) for k in ("nominal", "unusual", "mechanism", "missing"))
    assert "5 of the 5 other foods" in nominal[0] and "25% or more in nominal terms" in nominal[0]
    ex = doc["breadth"]["extent"]
    assert ex["n_elevated"] < ex["n_assessable"] / 2  # mostly ordinary for their own histories
    assert f"{ex['n_elevated']} of {ex['n_assessable']} assessable other foods were unusually high" in unusual_[0]
    assert any("not evidence against inflation or depreciation" in x for x in unusual_)
    assert mech[0].startswith("none:") and len(missing) == 2
    assert macro["status"] == "cannot_be_assessed"
    text = doc["evidence"]["conclusion"]["text"]
    assert "Several rose substantially in nominal terms (5 of 5" in text and "within their own usual ranges" in text


def test_foods_moving_together_is_not_evidence_for_inflation_without_a_price_index():
    others = {
        f"f{i}": (_meta(f"f{i}", f"Food {i}"), shock(series(132, seed=40 + i), "2019-03-01", 9, 1.6)) for i in range(5)
    }
    doc = _doc_with_foods(others)
    assert doc["breadth"]["extent"]["class"] == "broad"
    assert _macro(doc)["status"] == "cannot_be_assessed"  # it was "partly consistent" before
    assert _group(_macro(doc), "mechanism")[0].startswith("none:")


def test_with_a_price_index_the_macro_mechanism_is_assessed():
    cpi = {"yoy_pct": 0.5, "provider": "imf", "period": "2019-08-01"}
    doc = _doc_with_foods({})
    from market_almanac.analytics.evidence import build_evidence

    doc["context"]["macro"] = {"cpi": cpi, "fx": None, "real_yoy_pct": 0.05, "available": ["cpi"]}
    doc["magnitude"]["event_yoy_pct"] = 0.6
    macro = _macro({"evidence": build_evidence(doc)})
    assert macro["status"] == "consistent" and _group(macro, "mechanism")[0].startswith("national CPI changed")
    doc["context"]["macro"] = {"cpi": None, "fx": {"yoy_pct": 0.2}, "real_yoy_pct": None, "available": ["fx"]}
    assert _macro({"evidence": build_evidence(doc)})["status"] == "context_only"


def test_peer_population_is_reported_as_four_separate_counts():
    from market_almanac.analytics.evidence import population, population_text

    ext = {"n_peers": 60, "n_with_change": 41, "n_assessable": 22, "n_elevated": 18, "class": "widespread"}
    assert population(ext, 71) == {"found": 71, "read": 60, "observed": 41, "assessable": 22, "elevated": 18}
    t = population_text(ext, 71, "comparable markets", "high")
    assert t == (
        "71 comparable markets found (the 60 best observed were read); 41 reported a 12-month change within a month "
        "of the peak; 22 had enough history to be assessed against their own past; 18 of those 22 were also "
        "unusually high"
    )
    assert "(the" not in population_text({**ext, "n_peers": 71}, 71, "comparable markets", "high")


def test_the_evidence_never_describes_the_whole_country_from_the_assessable_markets_alone():
    peers = {
        f"p{i}": (_meta(f"p{i}", "Rice (imported)"), shock(series(132, seed=60 + i), "2019-03-01", 9, 1.6))
        for i in range(4)
    }
    doc = _doc_with_foods({}, peers=peers, peers_available=30)
    px_text = next(x["text"] for x in doc["evidence"]["quantitative"] if x["text"].startswith("Comparable markets"))
    assert "30 comparable markets found (the 4 best observed were read)" in px_text
    assert "describes only the 4 assessable markets, not every market in the country" in px_text
    concl = doc["evidence"]["conclusion"]["text"]
    assert "assessable comparable markets (of 30 found)" in concl
    assert doc["peers"]["n_available"] == 30


def test_robust_z_thresholds_are_described_as_screening_rules_not_probabilities():
    from market_almanac.analytics import shocks as sh

    others = {f"f{i}": (_meta(f"f{i}", f"Food {i}"), series(132, seed=40 + i)) for i in range(5)}
    doc = _doc_with_foods(others)
    blob = json.dumps(doc) + sh.__doc__ + sh.METHOD
    for banned in ("2.3%", "0.13%", "by chance", "normal distribution", "false-positive rate is"):
        assert banned not in blob.replace("no false-positive rate is claimed", ""), banned
    assert "screening rules, not calibrated significance tests" in doc["method"]["text"]
    assert doc["evidence"]["rules"]["screening"] == sh.SCREENING_CAVEAT
    assert any(
        "is a probability, significance level or false-positive rate" in x["text"]
        for x in doc["evidence"]["unsupported"]
    )


def test_an_episode_is_labelled_as_where_the_rule_fired_not_the_length_of_a_real_event():
    from market_almanac.analytics.shocks import EPISODE_CAVEAT

    others = {f"f{i}": (_meta(f"f{i}", f"Food {i}"), series(132, seed=40 + i)) for i in range(5)}
    doc = _doc_with_foods(others)
    assert doc["episode"] and doc["persistence"]["note"] == EPISODE_CAVEAT
    ev = doc["evidence"]
    assert any(EPISODE_CAVEAT in x["text"] for x in ev["quantitative"])
    assert any("full duration of a real-world disruption" in x["text"] for x in ev["unsupported"])
    assert "not the full duration of any event" in ev["conclusion"]["text"]
    assert "persisted for" not in ev["conclusion"]["text"] and "It lasted" not in ev["conclusion"]["text"]
    persistence = next(c for c in ev["assessment"] if c["key"] == "persistence")
    assert persistence["detail"].startswith("detected ") and "split or truncate" in persistence["detail"]


def test_large_but_ordinary_moves_of_other_foods_are_still_reported():
    from market_almanac.analytics.evidence import _median_clause

    calm = {"median_peer_yoy_pct": 0.03, "n_elevated": 0, "n_assessable": 3}
    big = {"median_peer_yoy_pct": 0.467, "n_elevated": 0, "n_assessable": 3}
    assert _median_clause(calm) == " (their median 12-month change was +3.0%)"
    assert "large but mostly within their own usual ranges" in _median_clause(big)
    assert _median_clause({"median_peer_yoy_pct": None}) == ""


def test_large_typical_means_within_the_usual_range_on_both_references():
    # noisy series: many large 12-month changes, some between the elevated (2) and trigger (3) thresholds
    p = series(132, seed=7, noise=0.12)
    sig = compute_signals(p)
    typical = [e for e in find_episodes(sig) if e["kind"] == "large_typical"]
    assert typical
    for e in typical:
        sgn = 1 if e["direction"] == "up" else -1
        assert abs(e["peak_z"]) < Z_ELEVATED  # against the changes before the movement began
        assert (sgn * sig.loc[e["start"] : e["end"], "z"]).max() < Z_ELEVATED  # against all earlier changes
