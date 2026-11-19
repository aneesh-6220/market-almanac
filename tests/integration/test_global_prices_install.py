"""Cold start on an ephemeral disk: build the data-only artefact, install it into an empty deployment, verify it."""

from __future__ import annotations

import hashlib
import tarfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from market_almanac.config import Settings
from market_almanac.data.public_bundle import BundleError, build_prices_bundle
from market_almanac.globaldata.release import install_prices, is_installed
from market_almanac.globaldata.shocks import SHOCK_CATALOG, SHOCK_MANIFEST, build_shock_catalog
from tests.global_support import build_catalog_for, obs_rows, write_country

G = "/api/v1/global"


@pytest.fixture(scope="module")
def artefact(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, dict]:
    src = tmp_path_factory.mktemp("src") / "data"
    write_country(src, "TST", obs_rows())
    write_country(src, "TSB", obs_rows(country="TSB", currency="TSH", base=50.0))
    build_catalog_for(src)
    build_shock_catalog(_settings(src), log=lambda *_: None)
    out = tmp_path_factory.mktemp("out")
    res = build_prices_bundle(src, "live", out)
    path = Path(res["archive"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == res["sha256"]
    return path, res["sha256"], res


def _settings(data: Path) -> Settings:
    return Settings(data_dir=data, market_almanac_mode="live", _env_file=None)  # type: ignore[call-arg,arg-type]


def test_artefact_holds_only_prices_and_is_small(artefact):
    path, _digest, res = artefact
    assert res["countries"] == 2 and res["observations"] == 60
    with tarfile.open(path) as t:
        names = t.getnames()
    assert any("partitions/prices/TST" in n for n in names) and any(
        n.endswith("global_series_catalog.parquet") for n in names
    )
    assert any(n.endswith(SHOCK_CATALOG) for n in names) and any(n.endswith(SHOCK_MANIFEST) for n in names)
    assert not any("weather" in n or ("series_catalog.parquet" in n and "global" not in n) for n in names)
    assert path.stat().st_size < 1_000_000


def test_manifest_names_only_what_the_artefact_contains_and_says_it_is_adapted(artefact):
    import json

    from market_almanac.data.public_bundle import MANIFEST_NAME

    path, _digest, _res = artefact
    with tarfile.open(path) as t:
        manifest = json.loads(t.extractfile(MANIFEST_NAME).read())  # type: ignore[union-attr]
    text = " ".join(manifest["attribution"])
    assert "World Food Programme" in text and "CC BY-IGO" in text
    for other in ("IMF", "NASA", "World Bank", "FAOSTAT", "MapSPAM"):  # none of these is in the price artefact
        assert other not in text
    assert manifest["adaptation_notice"].startswith("Adapted material")
    assert "endorsed" in manifest["adaptation_notice"]
    assert "code_commit" in manifest


def test_install_into_an_empty_directory_then_idempotent(artefact, tmp_path):
    path, digest, _ = artefact
    s = _settings(tmp_path / "data")
    assert not is_installed(s)
    r = install_prices(s, str(path), digest)
    assert r["format"] == "market-almanac-global-prices-1" and r["countries"] == 2
    assert is_installed(s)
    again = install_prices(s, str(path), digest)  # an install over itself changes nothing and does not fail
    assert again["countries"] == 2 and is_installed(s)


def test_a_volume_with_prices_but_no_episode_table_is_not_current(artefact, tmp_path):
    """An older artefact (v1) left on a persistent volume must not suppress the install of the episodes."""
    path, digest, _ = artefact
    s = _settings(tmp_path / "data")
    install_prices(s, str(path), digest)
    assert is_installed(s)
    (tmp_path / "data" / "public" / "live" / SHOCK_CATALOG).unlink()
    assert not is_installed(s)
    install_prices(s, str(path), digest)  # the missing file is added; nothing else is rewritten
    assert is_installed(s)


def test_wrong_checksum_installs_nothing(artefact, tmp_path):
    path, _, _ = artefact
    s = _settings(tmp_path / "data")
    with pytest.raises(BundleError, match=r"(?i)sha|checksum|mismatch"):
        install_prices(s, str(path), "0" * 64)
    assert not is_installed(s) and not (tmp_path / "data" / "lake").exists()


def test_checksum_is_mandatory(artefact, tmp_path):
    path, _, _ = artefact
    with pytest.raises(BundleError, match="SHA-256"):
        install_prices(_settings(tmp_path / "data"), str(path), None)


def test_a_non_price_artefact_is_refused(tmp_path):
    bogus = tmp_path / "x.tar.gz"
    with tarfile.open(bogus, "w:gz") as t:
        t.add(__file__, arcname="README")
    digest = hashlib.sha256(bogus.read_bytes()).hexdigest()
    with pytest.raises(BundleError):
        install_prices(_settings(tmp_path / "data"), str(bogus), digest)


def test_tampered_files_never_replace_existing_ones(artefact, tmp_path):
    path, digest, _ = artefact
    s = _settings(tmp_path / "data")
    install_prices(s, str(path), digest)
    victim = next((tmp_path / "data" / "lake").rglob("data.parquet"))
    before = victim.read_bytes()
    victim.write_bytes(before + b"x")  # corrupted in place
    with pytest.raises(BundleError):
        install_prices(s, str(path), digest)  # refuses to overwrite a differing immutable file
    assert victim.read_bytes() == before + b"x"


def test_app_cold_start_reports_503_then_ready_and_serves(artefact, tmp_path, monkeypatch):
    path, digest, _ = artefact
    data = tmp_path / "data"
    for k, v in {
        "DATA_DIR": str(data),
        "DATABASE_URL": f"sqlite:///{tmp_path}/api.db",
        "CACHE_DIR": str(tmp_path / "cache"),
        "MARKET_ALMANAC_MODE": "live",
        "GLOBAL_PRICES_BUNDLE_URL": str(path),
        "GLOBAL_PRICES_BUNDLE_SHA256": digest,
        "GLOBAL_PRICES_AUTO_INSTALL": "1",
        "API_RATE_LIMIT_PER_MINUTE": "1000000",
    }.items():
        monkeypatch.setenv(k, v)
    from market_almanac.config import reset_settings_cache
    from market_almanac_api.deps import BootstrapState, reset_global_prices
    from market_almanac_api.main import create_app

    reset_settings_cache()
    reset_global_prices()
    BootstrapState.prices_installing, BootstrapState.prices_error = False, None
    try:
        with TestClient(create_app(), raise_server_exceptions=False) as client:  # runs the lifespan
            assert client.get("/health").status_code == 200  # liveness never waits for data
            deadline = time.time() + 60
            while time.time() < deadline:
                r = client.get(f"{G}/countries")
                if r.status_code == 200:
                    break
                assert r.status_code == 503 and r.headers.get("retry-after"), r.text  # installing: retry, not an error
                time.sleep(0.1)
            assert r.status_code == 200 and len(r.json()["countries"]) == 2
            ready = client.get("/ready")
            body = ready.json()
            assert body["parts"]["prices"] == "ready", body
            sid = client.get(f"{G}/countries/TST/series").json()["items"][0]["series_id"]
            assert client.get(f"{G}/series/{sid}/observations").json()["total"] == 30
            shocks = client.get("/api/v1/shocks", params={"kind": "all", "direction": "any"})
            assert shocks.status_code == 200 and shocks.json()["stale_countries"] == []  # discovery ships with prices
        assert BootstrapState.prices_error is None
    finally:
        reset_settings_cache()
        reset_global_prices()
        BootstrapState.prices_installing = False


def test_bundle_refuses_a_missing_or_stale_shock_catalog(tmp_path):
    src = tmp_path / "data"
    write_country(src, "TST", obs_rows())
    build_catalog_for(src)
    with pytest.raises(BundleError, match="price-shock catalog is required"):
        build_prices_bundle(src, "live", tmp_path / "out")
    build_shock_catalog(_settings(src), log=lambda *_: None)
    write_country(src, "TSB", obs_rows(country="TSB", currency="TSH", base=50.0))  # a country added afterwards
    build_catalog_for(src)
    with pytest.raises(BundleError, match="different snapshots"):
        build_prices_bundle(src, "live", tmp_path / "out")


def test_episodes_carry_the_descriptors_of_their_series(artefact, tmp_path):
    import duckdb

    from market_almanac.globaldata.shocks import DESCRIPTORS

    path, digest, _ = artefact
    s = _settings(tmp_path / "data")
    install_prices(s, str(path), digest)
    pub = tmp_path / "data" / "public" / "live"
    cols = ", ".join(f"e.{c} IS NOT DISTINCT FROM c.{c}" for c in DESCRIPTORS)
    rows = duckdb.sql(
        f"SELECT {cols} FROM read_parquet('{pub / SHOCK_CATALOG}') e "
        f"JOIN read_parquet('{pub / 'global_series_catalog.parquet'}') c USING (series_id)"
    ).fetchall()
    assert all(all(r) for r in rows)
