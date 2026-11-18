"""Research workbench: specification rules, pooled inference properties, and end-to-end null/signal recovery.

The statistical tests simulate many datasets with known truth and check *rates*: how often the
pooled comparison declares an improvement when there is none (with markets in the same month
sharing shocks), and how often it finds a genuine one. The end-to-end test runs the complete
workbench on synthetic countries in which weather drives one commodity's prices and not another's.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from market_almanac.workbench import pooled
from market_almanac.workbench.spec import SpecError, parse_spec

BASE = """
id: test-study
title: Test predictive study
question: Does market-local weather improve one-month price forecasts?
hypothesis: Adding weather anomalies lowers out-of-sample squared error.
estimand: Ratio of country-balanced mean squared errors, family B over family A, h = 1.
study_type: predictive
population: {countries: [AAA, BBB, CCC, DDD, EEE]}
predictive:
  horizons: [1]
  families: [A, B]
  hypotheses:
    - {id: H1, statement: Family B forecasts beat family A at one month, challenger: B, baseline: A, horizon: 1}
"""


def _spec(**changes: object) -> str:
    import yaml

    d = yaml.safe_load(BASE)
    for k, v in changes.items():
        cur = d
        *path, last = k.split(".")
        for p in path:
            cur = cur.setdefault(p, {})
        cur[last] = v
    return yaml.safe_dump(d)


# ---------------------------------------------------------------- specification rules


def test_valid_spec_parses_and_hash_is_stable_and_sensitive():
    a, b = parse_spec(_spec()), parse_spec(_spec())
    assert a.spec_hash() == b.spec_hash()
    assert parse_spec(_spec(seed=1)).spec_hash() != a.spec_hash()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"predictive.evaluation": "random_split"}, "random train/test"),
        ({"study_type": "causal"}, "causal designs are not supported"),
        ({"estimand": "The causal effect of rainfall on maize prices"}, "causal language"),
        ({"predictive.families": ["B", "C"]}, "baseline family A"),
        ({"evidence_class": "confirmatory"}, "test_start"),
        ({"timing.price_release_lag_months": 2, "predictive.horizons": [1, 11]}, "may not exceed 12"),
        ({"population.require_coordinates": False}, "coordinates"),
        ({"descriptive": {"statistics": ["trend"]}}, "contradicts study_type"),
        ({"robustness": ["p_hacking"]}, "unknown robustness"),
        ({"population.countries": ["AAA", "../x"]}, "ISO3"),
    ],
)
def test_contradictory_specs_fail_with_reasons(change: dict[str, object], message: str):
    with pytest.raises(SpecError, match=message):
        parse_spec(_spec(**change))


def test_confirmatory_needs_correction_for_several_hypotheses():
    two = [
        {"id": "H1", "statement": "B beats A at one month", "challenger": "B", "baseline": "A", "horizon": 1},
        {"id": "H2", "statement": "B beats A at one month again", "challenger": "B", "baseline": "A", "horizon": 1},
    ]
    with pytest.raises(SpecError, match="multiplicity"):
        parse_spec(
            _spec(
                evidence_class="confirmatory",
                **{
                    "predictive.test_start": "2021-01-01",
                    "predictive.hypotheses": two,
                    "inference.multiplicity": "none",
                },
            )
        )


# ---------------------------------------------------------------- pooled inference (simulation)


def _rows(
    rng: np.random.Generator, effect: float, n_c: int = 6, n_s: int = 10, n_t: int = 60, month_sd: float = 1.0
) -> pd.DataFrame:
    """Loss rows with a shared month shock, a country shock and idiosyncratic noise.

    ``effect`` is the challenger's proportional loss reduction (0 = no signal).
    """
    origins = pd.date_range("2020-01-01", periods=n_t, freq="MS")
    month = rng.normal(0, month_sd, n_t)
    out = []
    for c in range(n_c):
        cshock = rng.normal(0, 0.3, n_t)
        for s in range(n_s):
            la = np.exp(rng.normal(0, 0.5, n_t)) * 2.0
            d = month + cshock + rng.normal(0, 0.5, n_t)  # mean-zero noise in the loss differential
            lb = la * (1 - effect) - 0.3 * d
            out.append(
                pd.DataFrame(
                    {
                        "country_iso3": f"C{c:02d}",
                        "series_id": f"C{c}_{s}",
                        "origin": origins,
                        "loss_a": la,
                        "loss_b": lb,
                    }
                )
            )
    return pd.concat(out, ignore_index=True)


def test_month_level_inference_controls_false_positives_under_shared_shocks():
    rng = np.random.default_rng(0)
    sims, alpha = 300, 0.05
    pooled_rejections = naive_rejections = 0
    for _ in range(sims):
        rows = _rows(rng, effect=0.0)
        r = pooled.compare(rows, 1, bootstrap="none", reps=200, min_periods=24)
        pooled_rejections += (r["p_challenger_better"] or 1) < alpha
        # the mistake this design avoids: treating every market-month forecast as independent
        d = rows["loss_a"] - rows["loss_b"]
        naive_rejections += stats.ttest_1samp(d, 0, alternative="greater").pvalue < alpha
    assert pooled_rejections / sims <= 0.09
    assert naive_rejections / sims >= 0.2  # demonstrably anti-conservative, hence not used


def test_injected_improvement_is_recovered():
    rng = np.random.default_rng(1)
    hits = sum(
        (pooled.compare(_rows(rng, effect=0.15), 1, bootstrap="none", reps=200)["p_challenger_better"] or 1) < 0.05
        for _ in range(60)
    )
    assert hits / 60 >= 0.8


def test_two_way_interval_covers_when_months_share_shocks_and_country_only_does_not():
    """Shocks common to all countries in a month are invisible to a country-only bootstrap.

    This test is why the default interval resamples countries *and* blocks of months: with a
    shared month shock the country-cluster interval covered the true ratio in under half of the
    simulations, the two-way interval in nearly all.
    """
    rng = np.random.default_rng(2)
    sims, two_way, country_only = 40, 0, 0
    for _ in range(sims):
        agg = pooled.aggregate(_rows(rng, effect=0.10, n_c=12, n_s=4, n_t=48, month_sd=0.3))
        tw = pooled.two_way_bootstrap(agg, 1, reps=300, seed=3, alpha=0.05)
        co = pooled.country_cluster_bootstrap(agg, reps=300, seed=3, alpha=0.05)
        two_way += tw["ci_low"] <= 0.90 <= tw["ci_high"]
        country_only += co["ci_low"] <= 0.90 <= co["ci_high"]
    assert two_way / sims >= 0.85
    assert country_only / sims < 0.7


def test_country_balanced_estimand_gives_each_country_equal_weight():
    t = pd.Timestamp("2021-01-01")
    rows = pd.DataFrame(
        {
            "country_iso3": ["BIG"] * 9 + ["SMALL"],
            "series_id": [f"b{i}" for i in range(9)] + ["s0"],
            "origin": [t] * 10,
            "loss_a": [1.0] * 10,
            "loss_b": [0.5] * 9 + [1.5],
        }
    )
    agg = pooled.aggregate(rows, "country_balanced")
    m = agg.groupby("origin")[["loss_a", "loss_b"]].mean()
    assert m["loss_b"].iloc[0] == pytest.approx(1.0)  # (0.5 + 1.5) / 2, not (9*0.5 + 1.5) / 10
    series = pooled.aggregate(rows, "series_pooled").groupby("origin")["loss_b"].mean().iloc[0]
    assert series == pytest.approx(0.6)


def test_multiplicity_adjustments_match_statsmodels():
    from statsmodels.stats.multitest import multipletests

    p = [0.01, 0.04, 0.03, 0.20, None]
    finite = [x for x in p if x is not None]
    for ours, theirs in (("holm", "holm"), ("benjamini_hochberg", "fdr_bh")):
        got = pooled.adjust(p, ours)
        ref = multipletests(finite, method=theirs)[1]
        assert got[-1] is None
        np.testing.assert_allclose([g for g in got if g is not None], ref, rtol=1e-12)


def test_matched_losses_use_a_common_sample_and_respect_the_test_start():
    o = pd.to_datetime(["2020-12-01", "2021-01-01", "2021-02-01"])
    preds = pd.DataFrame(
        {
            "country_iso3": "AAA",
            "series_id": "s",
            "origin": list(o) * 2,
            "model": ["ridge_A"] * 3 + ["ridge_B"] * 3,
            "pred": [0.0, 0.1, 0.2, 0.0, np.nan, 0.2],
            "y": [0.1, 0.1, 0.1] * 2,
            "task": "regression",
            "horizon": 1,
        }
    )
    m = pooled.matched_losses(preds, "ridge_A", "ridge_B", 1, pd.Timestamp("2021-01-01"))
    assert list(m["origin"]) == [pd.Timestamp("2021-02-01")]  # Dec excluded by test start, Jan by missing B
    assert m["loss_a"].iloc[0] == pytest.approx(0.01)


def test_evidence_wording_never_turns_a_null_into_absence():
    r = pooled.compare(_rows(np.random.default_rng(5), 0.0), 1, bootstrap="none", reps=200)
    ev = pooled.evidence(r, r["p_challenger_better"], 0.05, "challenger_better")
    assert ev["class"] == "not_established" and "not evidence" in ev["text"]
    assert pooled.evidence({"status": "insufficient_data"}, None, 0.05, "challenger_better")["class"] == (
        "insufficient_data"
    )


# ---------------------------------------------------------------- end to end on synthetic countries


SYNTH = ["XAA", "XBB", "XCC", "XDD", "XEE"]


def _synthetic_lake(settings) -> list[str]:  # type: ignore[no-untyped-def]
    """Five synthetic 'countries' from independent demo draws, each at its own coordinates."""
    from market_almanac.data.demo import generate_demo_datasets
    from market_almanac.data.identity import series_id, weather_location_id
    from market_almanac.globaldata.partitions import PartitionStore

    store = PartitionStore(settings.lake_dir, settings.market_almanac_mode.value)
    codes = SYNTH
    for k, code in enumerate(codes):
        d = generate_demo_datasets(seed=1000 + k)
        p, w = d["prices"].copy(), d["weather_monthly"].copy()
        p["country_iso3"] = code
        p["lat"] = p["lat"] + 3.0 * k
        w["lat"] = w["lat"] + 3.0 * k
        remap = {}
        for r in p.dropna(subset=["lat"]).drop_duplicates("market_code").itertuples():
            remap[weather_location_id(r.lat - 3.0 * k, r.lon)] = weather_location_id(r.lat, r.lon)
        w["location_id"] = w["location_id"].map(remap)
        w = w.dropna(subset=["location_id"])
        p["series_id"] = [
            series_id(
                provider=r.provider,
                country_iso3=code,
                market_code=r.market_code,
                commodity_code=r.commodity_code,
                unit=r.unit,
                price_type=r.price_type,
                price_flag=r.price_flag,
                currency=r.currency,
            )
            for r in p.itertuples()
        ]
        store.write("prices", code, p, provider="demo")
        store.write("weather_monthly", code, w, provider="demo")
    return codes


@pytest.mark.parametrize(("commodity", "expect_improvement"), [("DM-MAIZE", True), ("DM-RICE", False)])
def test_pipeline_recovers_injected_weather_signal_and_rejects_the_null(
    settings_factory, commodity: str, expect_improvement: bool
):
    from market_almanac.config import RunMode
    from market_almanac.workbench.execute import execute, studies_dir

    s = settings_factory(MARKET_ALMANAC_MODE=RunMode.DEMO)
    codes = _synthetic_lake(s)
    spec = parse_spec(
        _spec(
            id=f"e2e-{commodity.lower()}",
            negative_controls=["weather_time_shift_60"],
            **{
                "population.countries": codes,
                "population.commodity_codes": [commodity],
                "population.min_eligible_series_per_group": 3,
                "predictive.min_test_periods": 24,
                "inference.bootstrap_reps": 200,
            },
        )
    )
    res = execute(s, spec, workers=2)
    h1 = res["hypotheses"][0]
    assert h1["result"]["n_countries"] == 5
    if expect_improvement:
        assert h1["evidence"]["class"].startswith("improvement"), h1
        placebo = next(v for v in res["variants"] if v["variant"] == "weather_time_shift_60")
        assert placebo["loss_ratio"] > h1["result"]["loss_ratio"]  # shifted weather loses the signal
    else:
        assert h1["evidence"]["class"] in ("not_established", "deterioration"), h1
    root = studies_dir(s) / spec.id
    from market_almanac.workbench.package import verify_package

    assert verify_package(root)["ok"]
    crate = json.loads((root / "ro-crate-metadata.json").read_text())
    assert crate["@context"] == "https://w3id.org/ro/crate/1.2/context"
    assert "Loss ratio" in (root / "report.md").read_text()


def test_confirmatory_run_requires_an_unchanged_freeze(settings_factory, monkeypatch: pytest.MonkeyPatch):
    from market_almanac.config import RunMode
    from market_almanac.workbench import execute as ex

    s = settings_factory(MARKET_ALMANAC_MODE=RunMode.DEMO)
    _synthetic_lake(s)
    conf = parse_spec(
        _spec(
            id="conf-study",
            evidence_class="confirmatory",
            **{
                "predictive.test_start": "2021-01-01",
                "population.commodity_codes": ["DM-MAIZE"],
                "population.countries": SYNTH,
                "population.min_eligible_series_per_group": 3,
            },
        )
    )
    with pytest.raises(ex.FreezeError, match="freeze the specification first"):
        ex.execute(s, conf)
    monkeypatch.setattr(ex, "code_provenance", lambda: {"git_commit": "abc", "dirty": False})
    rec = ex.freeze(s, conf)
    assert rec["groups"] and rec["outcomes_inspected_before_freeze"] is False
    changed = parse_spec(
        _spec(
            id="conf-study",
            evidence_class="confirmatory",
            seed=7,
            **{
                "predictive.test_start": "2021-01-01",
                "population.commodity_codes": ["DM-MAIZE"],
                "population.countries": SYNTH,
                "population.min_eligible_series_per_group": 3,
            },
        )
    )
    with pytest.raises(ex.FreezeError, match="different specification"):
        ex.freeze(s, changed)
    with pytest.raises(ex.FreezeError, match="changed after it was frozen"):
        ex.execute(s, changed)
    monkeypatch.setattr(ex, "code_provenance", lambda: {"git_commit": "abc", "dirty": True})
    # regression (audit v1.1): a frozen confirmatory study must not execute from an uncommitted tree
    with pytest.raises(ex.FreezeError, match="executed from a committed, clean git tree"):
        ex.execute(s, conf)
    monkeypatch.setattr(ex, "code_provenance", lambda: {"git_commit": None, "dirty": None})
    with pytest.raises(ex.FreezeError, match="executed from a committed, clean git tree"):
        ex.execute(s, conf)
    monkeypatch.setattr(ex, "code_provenance", lambda: {"git_commit": "abc", "dirty": True})
    with pytest.raises(ex.FreezeError, match="clean git tree"):
        ex.freeze(
            s,
            parse_spec(
                _spec(id="conf-dirty", evidence_class="confirmatory", **{"predictive.test_start": "2021-01-01"})
            ),
        )


def test_package_verification_detects_tampering_and_escaping_paths(tmp_path: Path):
    from market_almanac.workbench.package import verify_package, write_package

    spec = parse_spec(_spec())
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "results.json").write_text(json.dumps({"hypotheses": [], "multiplicity": {"method": "holm", "family": []}}))
    write_package(None, spec, root)
    assert verify_package(root)["ok"]
    (root / "results.json").write_text("{}")
    assert verify_package(root)["changed"] == ["results.json"]
    (root / "SHA256SUMS").write_text((root / "SHA256SUMS").read_text() + "0" * 64 + "  ../../etc/passwd\n")
    out = verify_package(root)
    assert "../../etc/passwd" in out["changed"] and not out["ok"]
