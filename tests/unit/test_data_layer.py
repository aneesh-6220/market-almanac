from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_almanac.data.alignment import RULES, asof_align
from market_almanac.data.quality import (
    EligibilityCriteria,
    assess_prices,
    build_quality_report,
    classify_extremes,
    clean_monthly_series,
)
from market_almanac.data.schema import PRICES, SchemaError, coerce, validate
from market_almanac.data.store import DatasetStore
from market_almanac.data.weather import aggregate_daily_to_monthly
from market_almanac.evaluation.inference import diebold_mariano, moving_block_bootstrap_ratio, newey_west_variance
from market_almanac.evaluation.metrics import calibration_table, classification_metrics, regression_metrics


def _prices(
    n: int = 60,
    unit: str = "KG",
    market: str = "M1",
    series: str | None = None,
    start: str = "2015-01-01",
    values: np.ndarray | None = None,
) -> pd.DataFrame:
    from market_almanac.data.identity import series_id

    periods = pd.date_range(start, periods=n, freq="MS")
    sid = series or series_id(
        provider="t",
        country_iso3="KEN",
        market_code=market,
        commodity_code="1",
        unit=unit,
        price_type="Retail",
        price_flag="actual",
        currency="KES",
    )
    v = values if values is not None else 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.02, n)))
    return coerce(
        pd.DataFrame(
            {
                "series_id": sid,
                "provider": "t",
                "country_iso3": "KEN",
                "market_code": market,
                "market_name": market,
                "lat": 1.0,
                "lon": 36.0,
                "commodity_code": "1",
                "commodity_name": "Maize",
                "commodity_category": "c",
                "unit": unit,
                "price_type": "Retail",
                "price_flag": "actual",
                "currency": "KES",
                "period": periods,
                "price": v,
                "retrieved_at": pd.Timestamp("2025-01-01", tz="UTC"),
                "quality_flags": "",
            }
        ),
        PRICES,
    )


def test_schema_validation_errors():
    df = _prices(5)
    validate(df, PRICES)
    with pytest.raises(SchemaError, match="duplicate"):
        validate(pd.concat([df, df.iloc[[0]]]), PRICES)
    bad = df.copy()
    bad.loc[0, "period"] = pd.Timestamp("2015-01-15")
    with pytest.raises(SchemaError, match="first day"):
        validate(bad, PRICES)
    with pytest.raises(SchemaError, match="missing columns"):
        validate(df.drop(columns=["unit"]), PRICES)


def test_store_snapshots_are_immutable_and_idempotent(tmp_path):
    st = DatasetStore(tmp_path, "test")
    a = st.write("prices", _prices(10), providers=["t"])
    b = st.write("prices", _prices(10), providers=["t"])  # identical refresh
    assert a.snapshot_id != b.snapshot_id and a.content_hash == b.content_hash
    assert b.parent_snapshot_id == a.snapshot_id
    c = st.write("prices", _prices(14), providers=["t"])  # incremental: 4 new months
    assert c.row_count == 14
    assert len(st.read("prices", a.snapshot_id)) == 10  # old snapshot unchanged
    q = st.query("SELECT count(*) AS n FROM prices WHERE price > ?", [0], datasets=("prices",))
    assert int(q["n"].iloc[0]) == 14
    assert st.prune("prices", keep=1) == 2


def test_quality_gaps_coverage_and_eligibility():
    df = _prices(60)
    df = df[~df["period"].isin(pd.date_range("2017-01-01", periods=8, freq="MS"))]
    [q], _ = assess_prices(df)
    assert q.longest_gap_months == 8 and not q.eligible
    assert any("gap" in r for r in q.reasons)
    [ok], _ = assess_prices(_prices(60))
    assert ok.eligible
    [short], _ = assess_prices(_prices(20))
    assert not short.eligible
    nocoord = _prices(60)
    nocoord["lat"] = np.nan
    [nc], _ = assess_prices(nocoord, EligibilityCriteria())
    assert not nc.has_coordinates and not nc.eligible


def test_extremes_are_flagged_not_removed():
    v = np.full(40, 100.0)
    v[20] = 300.0  # one-month spike that reverses -> candidate measurement anomaly
    df = _prices(40, values=v)
    monthly = clean_monthly_series(df)
    ext = classify_extremes(monthly, df.drop_duplicates("series_id"))
    assert "reversing_spike" in set(ext["classification"])
    assert monthly["price"].max() == 300.0  # still present
    rep = build_quality_report({"prices": df})
    assert rep["summary"]["extreme_changes"] >= 1


def test_corroborated_shock_classification():
    base = np.r_[np.full(20, 100.0), np.full(20, 160.0)]  # persistent jump in two markets
    df = pd.concat([_prices(40, market="A", values=base), _prices(40, market="B", values=base * 1.1)])
    ext = classify_extremes(clean_monthly_series(df), df.drop_duplicates("series_id"))
    assert set(ext["classification"]) == {"corroborated_shock"}


def test_monthly_weather_aggregation_completeness():
    days = pd.date_range("2020-01-01", "2020-02-29", freq="D")
    d = pd.DataFrame({"date": days, "PRECTOTCORR": 2.0, "T2M": 20.0, "T2M_MAX": 36.0, "T2M_MIN": 10.0})
    d.loc[d["date"] >= "2020-02-10", ["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN"]] = np.nan
    m = aggregate_daily_to_monthly(d)
    jan, feb = m.iloc[0], m.iloc[1]
    assert jan["complete"] and jan["precip_total_mm"] == pytest.approx(62.0)
    assert jan["heat_days_t2m_max_ge_35c"] == pytest.approx(31.0)
    assert not feb["complete"] and np.isnan(feb["precip_total_mm"])  # never extrapolated


def test_annual_alignment_rule():
    rule = RULES["faostat_annual"]
    vals = pd.DataFrame({"period": [pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01")], "value": [1.0, 2.0]})
    origins = pd.Series(pd.to_datetime(["2021-11-01", "2021-12-01", "2022-12-01"]))
    out = asof_align(origins, vals, rule, published_col=None)
    assert np.isnan(out.iloc[0]) and out.iloc[1] == 1.0 and out.iloc[2] == 2.0


def test_metrics_and_suppression():
    y = np.array([0.1, -0.1, 0.2, 0.0] * 10)
    p = y + 0.01
    m = regression_metrics(y, p, naive_mae=0.1, naive_rmse=0.12)
    assert m["mae"] == pytest.approx(0.01) and m["bias"] == pytest.approx(0.01)
    assert m["relative_mae"] == pytest.approx(0.1)
    yc = np.r_[np.ones(3), np.zeros(97)]
    c = classification_metrics(yc, np.full(100, 0.03), 0.5, base_rate_brier=0.03, min_events=10)
    assert c["pr_auc"] is None and "suppressed_reason" in c  # too few events
    cal = calibration_table(yc, np.full(100, 0.03))
    assert cal[0]["count"] == 100 and cal[1]["count"] == 0


def test_diebold_mariano_behaviour():
    rng = np.random.default_rng(0)
    dates = pd.Series(pd.date_range("2010-01-01", periods=120, freq="MS"))
    la = pd.Series(rng.chisquare(1, 120))
    same = diebold_mariano(la, la * 1.0, dates, h=1)
    assert same.stat is None  # zero variance: refuses rather than inventing significance
    lb = la * 0.5
    better = diebold_mariano(la, lb + rng.normal(0, 0.01, 120) ** 2, dates, h=3)
    assert better.p_value_b_better is not None and better.p_value_b_better < 0.01 and better.lags >= 2
    noise = diebold_mariano(la, pd.Series(rng.chisquare(1, 120)), dates, h=1)
    assert noise.p_value_two_sided is not None and noise.p_value_two_sided > 0.01
    few = diebold_mariano(la[:10], lb[:10], dates[:10], h=1)
    assert few.stat is None and "insufficient" in few.note
    assert newey_west_variance(np.ones(10), 3) == pytest.approx(0.0)
    b = moving_block_bootstrap_ratio(la, lb, dates, h=1, reps=200)
    assert b["ci_low"] <= 0.5 <= b["ci_high"]
