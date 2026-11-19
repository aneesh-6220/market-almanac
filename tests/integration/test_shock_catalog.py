"""Offline shock catalog: peer groups respect units and currencies, builds are deterministic, revisions show."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_almanac.analytics.investigation import config_id
from market_almanac.globaldata.shocks import build_country, stale_countries


def _raw(sid: str, n: int = 120, seed: int = 0, shock_at: int | None = None, factor: float = 1.8) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2014-01-01", periods=n, freq="MS")
    p = 100 * np.exp(rng.normal(0, 0.03, n))
    if shock_at is not None:
        p[shock_at : shock_at + 6] *= factor
    return pd.DataFrame({"series_id": sid, "country_iso3": "TST", "period": idx, "price": p, "quality_flags": ""})


def _meta(rows: list[tuple[str, str, str, str, str]]) -> pd.DataFrame:
    return (
        pd.DataFrame(rows, columns=["series_id", "commodity_code", "unit", "price_type", "currency"])
        .assign(country_iso3="TST")
        .set_index("series_id")
    )


def test_peer_groups_never_mix_units_price_types_or_currencies():
    ids = ["a", "b", "c", "d", "e"]
    raw = pd.concat([_raw(s, seed=i, shock_at=80) for i, s in enumerate(ids)])
    meta = _meta(
        [
            ("a", "1", "KG", "Retail", "XOF"),
            ("b", "1", "KG", "Retail", "XOF"),
            ("c", "1", "50 KG", "Retail", "XOF"),  # different unit
            ("d", "1", "KG", "Wholesale", "XOF"),  # different price type
            ("e", "1", "KG", "Retail", "USD"),  # different currency
        ]
    )
    df = build_country(raw, meta, "snap1", "TST")
    up = df[(df["kind"] == "unusual") & (df["direction"] == "up") & (df["start"] == "2020-09-01")]
    up = up.set_index("series_id")
    assert set(up.index) == set(ids)
    assert up.loc["a", "peer_n"] == 1 and up.loc["b", "peer_n"] == 1
    assert (up.loc[["c", "d", "e"], "peer_n"] == 0).all()
    assert (up.loc[["c", "d", "e"], "extent"] == "inconclusive").all()


def test_widespread_versus_local_in_the_catalog():
    shocked = [_raw(f"s{i}", seed=i, shock_at=80) for i in range(6)]
    calm = [_raw(f"c{i}", seed=100 + i) for i in range(6)]
    lone = _raw("lone", seed=50, shock_at=60)
    raw = pd.concat([*shocked, *calm, lone])
    meta = _meta([(s, "1", "KG", "Retail", "XOF") for s in raw["series_id"].unique()])
    df = build_country(raw, meta, "snap1", "TST")
    up = df[(df["kind"] == "unusual") & (df["direction"] == "up") & (df["start"] == "2020-09-01")]
    assert set(up["series_id"]) >= {f"s{i}" for i in range(6)}
    assert set(up.loc[up["series_id"].str.startswith("s"), "extent"]) == {"mixed"}  # 5 of 12 peers elevated
    lone_ep = df[(df["series_id"] == "lone") & (df["kind"] == "unusual") & (df["start"] == "2019-01-01")]
    assert len(lone_ep) == 1 and lone_ep.iloc[0]["extent"] == "local"


def test_build_is_deterministic_and_a_revision_changes_it():
    raw = pd.concat([_raw("a", seed=1, shock_at=80), _raw("b", seed=2, shock_at=80), _raw("c", seed=3)])
    meta = _meta([(s, "1", "KG", "Retail", "XOF") for s in "abc"])
    one = build_country(raw, meta, "snap1", "TST")
    two = build_country(raw.sample(frac=1, random_state=0), meta, "snap1", "TST")  # input order does not matter
    pd.testing.assert_frame_equal(one.reset_index(drop=True), two.reset_index(drop=True))
    revised = raw.copy()
    revised.loc[(revised["series_id"] == "c") & (revised["period"] == "2020-10-01"), "price"] *= 3
    three = build_country(revised, meta, "snap2", "TST")
    assert not three.drop(columns="snapshot_id").equals(one.drop(columns="snapshot_id"))
    assert set(three["snapshot_id"]) == {"snap2"}


def test_invalid_records_never_enter_the_catalog():
    raw = _raw("a", seed=1)
    raw.loc[60, "price"] = 0.0
    raw.loc[61, "quality_flags"] = "invalid_price"
    raw.loc[61, "price"] = 1e9
    raw.loc[62, "quality_flags"] = "duplicate_conflict"
    raw.loc[62, "price"] = 1e9
    df = build_country(raw, _meta([("a", "1", "KG", "Retail", "XOF")]), "snap1", "TST")
    assert df.empty or not (df["data_concern"] & (df["kind"] == "unusual")).any()


def test_snapshot_identity():
    manifest = {"countries": {"AAA": {"snapshot_id": "s1"}, "BBB": {"snapshot_id": "s2"}}}
    assert stale_countries(manifest, {"AAA": "s1", "BBB": "s2"}) == []
    assert stale_countries(manifest, {"AAA": "s1", "BBB": "s3"}) == ["BBB"]
    assert stale_countries(manifest, {"AAA": "s1"}) == ["BBB"]
    cfg = {
        "series_id": "ps_x",
        "event": "2022-05",
        "window": {"start": "2020-05", "end": "2023-05"},
        "snapshot_id": "a",
    }
    assert config_id(cfg) == config_id(dict(reversed(list(cfg.items()))))  # key order does not matter
    assert config_id(cfg) != config_id({**cfg, "snapshot_id": "b"})  # a data revision is a different analysis
