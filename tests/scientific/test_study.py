"""The pre-specified study: specification, falsification variants and the decision rule."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from shocktrace.geo.spam import packaged_weights
from shocktrace.research.report import render_markdown
from shocktrace.research.study import (
    MIN_NATIONAL_AREA_HA,
    PLACEBO_SHIFT_MONTHS,
    STUDY,
    VARIANTS,
    WRONG_CROP,
    decide,
    experiment_id,
    overall_outcome,
    placebo_features,
    variant_config,
)

CROP_OF = {"73": "millet", "65": "sorghum", "135": "sorghum", "51": "maize", "67": "maize", "120": "cowpea"}


def test_study_specification_matches_the_protocol():
    assert STUDY.study_id == "sahel-production-weather-v1"
    assert STUDY.horizons == (1, 3) and STUDY.primary_lag == 1 and STUDY.sensitivity_lags == (0, 2)
    assert set(STUDY.exploratory) == {"BFA"} and set(STUDY.confirmatory) == {"MLI", "NER"}
    conf = STUDY.cells("confirmatory")
    assert [c for c in conf if c[2] == "confirmatory"] == [
        ("MLI", "73", "confirmatory"),
        ("MLI", "65", "confirmatory"),
        ("MLI", "51", "confirmatory"),
        ("MLI", "120", "confirmatory"),
        ("NER", "73", "confirmatory"),
        ("NER", "65", "confirmatory"),
    ]
    assert ("NER", "51", "exploratory") in conf  # Niger maize is reported but never confirmatory
    assert all(c[2] == "exploratory" for c in STUDY.cells("exploratory"))


def test_confirmatory_crops_meet_the_production_scale_threshold():
    w = packaged_weights()
    area = w.groupby(["country_iso3", "crop"])["area_ha"].sum()
    for country, codes in STUDY.confirmatory.items():
        for code in codes:
            assert area[(country, CROP_OF[code])] >= MIN_NATIONAL_AREA_HA
    assert area[("NER", "maize")] < MIN_NATIONAL_AREA_HA  # the reason Niger maize is secondary


def test_variant_configurations():
    prim = variant_config(STUDY, "MLI", "73", "MLI: Millet", "confirmatory", "primary")
    assert prim.price_release_lag_months == 1 and prim.families == ["A", "B", "P"] and not prim.include_trees
    assert prim.evidence_class == "confirmatory" and prim.study == STUDY.study_id and prim.use_precip_qc
    assert variant_config(STUDY, "MLI", "73", "n", "confirmatory", "lag0").price_release_lag_months == 0
    assert variant_config(STUDY, "MLI", "73", "n", "confirmatory", "lag2").price_release_lag_months == 2
    assert variant_config(STUDY, "MLI", "73", "n", "confirmatory", "rawprecip").use_precip_qc is False
    for v in VARIANTS[1:]:  # only the primary run on a confirmatory cell counts as confirmatory evidence
        assert variant_config(STUDY, "MLI", "73", "n", "confirmatory", v).evidence_class == "exploratory"
    ids = {experiment_id(STUDY, c, k, v) for c, k, _ in STUDY.cells("all") for v in VARIANTS}
    assert len(ids) == len(STUDY.cells("all")) * len(VARIANTS)
    assert all(re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", i) for i in ids)


def _weather(seed: int = 1) -> pd.DataFrame:
    w = packaged_weights()
    cells = w[w["country_iso3"] == "NER"]["location_id"].unique()
    months = pd.date_range("1991-01-01", "2025-12-01", freq="MS")
    rng = np.random.default_rng(seed)
    wet = np.isin(months.month, [6, 7, 8, 9, 10])
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "location_id": c,
                    "period": months,
                    "precip_total_mm": np.where(wet, rng.gamma(5.0, 20.0, len(months)), 0.0),
                    "heat_days_t2m_max_ge_35c": rng.integers(0, 31, len(months)).astype(float),
                }
            )
            for c in cells
        ],
        ignore_index=True,
    )


def test_time_shift_placebo_keeps_the_calendar_and_uses_only_older_weather():
    from shocktrace.features.production_weather import build_production_features

    wx = _weather()
    real, _ = build_production_features(wx, "NER", {"73": "Millet"})
    fake = placebo_features("placebo_shift", wx, "NER", "73", "Millet")
    r, f = real.set_index("period"), fake.set_index("period")
    t = pd.Timestamp("2022-08-01")
    back = t - pd.DateOffset(months=PLACEBO_SHIFT_MONTHS)
    for c in ("c_rain_season_anom", "c_rain_season_anom_prev", "c_heat_season_anom", "c_rain_onset_anom"):
        assert f.loc[t, c] == pytest.approx(r.loc[back, c])
    pd.testing.assert_series_equal(f["c_in_season"], r["c_in_season"])
    pd.testing.assert_series_equal(f["c_months_since_harvest"], r["c_months_since_harvest"])
    # changing weather from 2020 on cannot change the placebo before 2025
    late = wx.copy()
    late.loc[late["period"] >= "2020-01-01", "precip_total_mm"] *= 9
    f2 = placebo_features("placebo_shift", late, "NER", "73", "Millet").set_index("period")
    pd.testing.assert_frame_equal(f.loc[:"2024-12-01"], f2.loc[:"2024-12-01"])


def test_wrong_crop_placebo_swaps_weights_but_keeps_the_commodity():
    wx = _weather()
    fake = placebo_features("placebo_crop", wx, "NER", "73", "Millet")
    assert set(fake["commodity_code"]) == {"73"} and WRONG_CROP["millet"] == "maize"
    assert placebo_features("placebo_crop", wx, "NER", "64", "Rice (imported)") is None
    assert placebo_features("primary", wx, "NER", "73", "Millet") is None
    assert all(WRONG_CROP[WRONG_CROP[c]] == c for c in WRONG_CROP)  # the swap is an involution


def _test_row(**kw):  # type: ignore[no-untyped-def]
    base = {
        "country": "MLI",
        "horizon": 1,
        "contrast": "P_vs_A",
        "variant": "primary",
        "loss_ratio": 0.95,
        "ci_low": 0.91,
        "ci_high": 0.99,
        "p_b_better": 0.001,
        "p_holm": 0.008,
        "subperiod_mean_diff": [0.001, 0.002],
        "fragile": False,
    }
    return {**base, **kw}


def _placebo(p: float, country: str = "MLI", h: int = 1):  # type: ignore[no-untyped-def]
    return {"country": country, "horizon": h, "variant": "placebo_shift", "p_b_better": p}


def test_decision_rule_requires_every_precommitted_condition():
    ok = decide(_test_row(), [_placebo(0.01)], 0.05)
    assert ok["outcome"] == "improvement_established"
    cases = {
        "holm": (_test_row(p_holm=0.20), [_placebo(0.01)], "no_established_improvement"),
        "halves": (_test_row(subperiod_mean_diff=[0.003, -0.001]), [_placebo(0.01)], "significant_but_unconfirmed"),
        "placebo": (_test_row(), [_placebo(0.40)], "significant_but_unconfirmed"),
        "no placebo run": (_test_row(), [], "significant_but_unconfirmed"),
        "placebo of another country": (_test_row(), [_placebo(0.01, "NER")], "significant_but_unconfirmed"),
        "fragile": (_test_row(fragile=True), [_placebo(0.01)], "significant_but_unconfirmed"),
        "worse": (_test_row(loss_ratio=1.05), [_placebo(0.01)], "no_established_improvement"),
    }
    for name, (row, pooled, expected) in cases.items():
        assert decide(row, pooled, 0.05)["outcome"] == expected, name


def test_study_outcome_wording_never_claims_absence_of_effect():
    null = [decide(_test_row(p_holm=0.9, loss_ratio=1.01), [], 0.05) for _ in range(8)]
    out = overall_outcome(null)
    assert out["label"] == "no_established_improvement" and out["n_holm_significant"] == 0
    assert "not evidence that weather has no effect" in out["statement"]
    mixed = [*null[:7], decide(_test_row(fragile=True), [_placebo(0.01)], 0.05)]
    assert overall_outcome(mixed)["label"] == "inconclusive"
    assert overall_outcome([*null[:7], decide(_test_row(), [_placebo(0.01)], 0.05)])["label"] == "positive"
    assert overall_outcome([])["label"] == "not_run"


def test_report_tables_render_from_results():
    row = {
        **_test_row(),
        "evidence_class": "confirmatory",
        "n_months": 66,
        "n_rows": 12345,
        "model_a": "ridge_A",
        "model_b": "ridge_P",
    }
    res = {
        "study_id": STUDY.study_id,
        "phase": "confirmatory",
        "spec": {"primary_lag": 1},
        "pooled": [row],
        "per_crop": [{**row, "commodity_code": "73"}],
        "experiments": [
            {
                "experiment_id": "e1",
                "country": "MLI",
                "commodity_code": "73",
                "commodity_name": "Millet",
                "variant": "primary",
                "evidence_class": "confirmatory",
                "n_series": 58,
            }
        ],
        "confirmatory": {
            "n_tests": 1,
            "decisions": [decide(row, [_placebo(0.01)], 0.05)],
            "outcome": {"label": "positive", "statement": "s"},
        },
    }
    md = render_markdown(res)
    assert "| MLI | production-region weather vs price history (P vs A) | 1 | 66 | 12,345 | 0.950 |" in md
    assert "0.910 to 0.990" in md and "| MLI | Millet | P vs A |" in md and "improvement established" in md
