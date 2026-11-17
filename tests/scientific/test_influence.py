"""Influence diagnostics: does a comparison depend on one month, one market or one cell?"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_almanac.evaluation.influence import _loo, influence_report


def _rows(n_months: int = 40, n_series: int = 5) -> pd.DataFrame:
    months = pd.date_range("2021-01-01", periods=n_months, freq="MS")
    return pd.DataFrame(
        [
            {"origin": m, "series_id": f"s{i}", "location_id": f"c{i % 3}", "la": 1.0, "lb": 1.0, "qc_flag": 0.0}
            for m in months
            for i in range(n_series)
        ]
    )


def test_leave_one_out_arithmetic():
    # groups with sums a = [1,1,2], b = [1,3,2]: full ratio 6/4; dropping group 2 gives 3/3
    np.testing.assert_allclose(_loo(np.array([1.0, 1, 2]), np.array([1.0, 3, 2])), [5 / 3, 1.0, 2.0])


def test_single_month_driving_the_ratio_is_fragile():
    """Mirrors the v0.1 defect: one origin month (a spurious rainfall value) produced the headline ratio."""
    df = _rows()
    bad = pd.Timestamp("2023-12-01")
    df.loc[df["origin"] == bad, "lb"] = 30.0
    df.loc[df["origin"] == bad, "qc_flag"] = 1.0
    r = influence_report(df)
    assert r["ratio"] == pytest.approx((39 * 5 + 150) / 200)
    top = r["months"]["top"][0]
    assert top["origin"] == "2023-12-01"
    assert top["ratio_without"] == pytest.approx(1.0)
    assert top["share_of_excess_loss"] == pytest.approx(1.0)
    assert r["months"]["ratio_without_top_k"] == pytest.approx(1.0)
    assert r["qc_flagged_rows"] == {"n_flagged": 5, "ratio_excluding_flagged": pytest.approx(1.0)}
    assert r["fragile"] and any("origin months" in s for s in r["reasons"])
    assert any("QC-flagged" in s for s in r["reasons"])


def test_broad_based_effect_is_not_fragile():
    rng = np.random.default_rng(0)
    df = _rows(60, 20)
    df["la"] = rng.gamma(4.0, 0.25, len(df))
    df["lb"] = df["la"] * rng.normal(0.9, 0.02, len(df))  # B better by ~10% everywhere
    r = influence_report(df)
    assert r["ratio"] == pytest.approx(0.9, abs=0.01)
    assert not r["fragile"] and r["reasons"] == []
    assert r["months"]["max_single_month_shift"] < 0.01
    assert r["series"]["n_groups"] == 20 and r["cells"]["n_groups"] == 3


def test_single_market_or_cell_driving_the_ratio_is_fragile():
    df = _rows()
    df.loc[df["series_id"] == "s4", "lb"] = 2.0  # one market accounts for the whole difference
    r = influence_report(df)
    assert r["ratio"] == pytest.approx(1.2)
    assert r["series"]["most_influential"] == "s4"
    assert r["series"]["ratio_without_most_influential"] == pytest.approx(1.0)
    assert r["fragile"] and any("price series" in s for s in r["reasons"])


def test_null_result_is_not_called_fragile_for_trivial_shifts():
    rng = np.random.default_rng(4)
    df = _rows(68, 50)
    df["la"] = rng.gamma(2.0, 0.5, len(df))
    df["lb"] = df["la"] * rng.normal(1.005, 0.05, len(df))
    r = influence_report(df)
    assert abs(r["ratio"] - 1) < 0.02 and r["fragility_threshold"] == pytest.approx(0.02)
    assert not r["fragile"]


def test_empty_or_degenerate_input():
    assert (
        influence_report(pd.DataFrame(columns=["origin", "series_id", "la", "lb"]))["status"] == "insufficient_evidence"
    )
