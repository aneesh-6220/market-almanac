"""Public data bundle: round trip, verification and refusal to overwrite immutable artefacts."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from market_almanac.data.public_bundle import BundleError, build_bundle, install_bundle


def _seed(root: Path) -> None:
    for rel, body in {
        "lake/live/prices/snap1/data.parquet": b"PAR1prices",
        "lake/live/prices/snap1/manifest.json": b'{"snapshot_id": "snap1"}',
        "public/live/manifest.json": b"{}",
        "experiments/live/exp_a/results.json": b'{"experiment_id": "exp_a"}',
        "experiments/live/exp_a/predictions.parquet": b"PAR1preds",
        "experiments/live/exp_a/features.parquet": b"PAR1features-not-shipped",
        "experiments/live/studies/s1/results_confirmatory.json": b"{}",
        "cache/http/secretish": b"never shipped",
        "lake/demo/prices/x/data.parquet": b"other mode",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)


def test_round_trip_contents_and_exclusions(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    _seed(src)
    res = build_bundle(src, "live", tmp_path / "dist")
    with tarfile.open(res["archive"]) as tar:
        names = set(tar.getnames())
    assert "experiments/live/exp_a/predictions.parquet" in names
    assert "experiments/live/studies/s1/results_confirmatory.json" in names
    assert not any("features.parquet" in n or n.startswith("cache/") or "/demo/" in n for n in names)

    out = install_bundle(res["archive"], dst, res["sha256"])
    assert out["written"] == res["n_files"] and out["already_present"] == 0
    assert (dst / "lake/live/prices/snap1/data.parquet").read_bytes() == b"PAR1prices"
    again = install_bundle(res["archive"], dst)  # idempotent
    assert again["written"] == 0
    assert json.loads((dst / "bundles/live-installed.json").read_text())["archive_sha256"] == res["sha256"]


def test_wrong_archive_hash_is_rejected(tmp_path: Path) -> None:
    _seed(tmp_path / "src")
    res = build_bundle(tmp_path / "src", "live", tmp_path / "dist")
    with pytest.raises(BundleError, match="does not match"):
        install_bundle(res["archive"], tmp_path / "dst", "0" * 64)


def test_differing_installed_file_is_never_overwritten(tmp_path: Path) -> None:
    _seed(tmp_path / "src")
    res = build_bundle(tmp_path / "src", "live", tmp_path / "dist")
    dst = tmp_path / "dst"
    (dst / "experiments/live/exp_a").mkdir(parents=True)
    (dst / "experiments/live/exp_a/results.json").write_text('{"tampered": true}')
    with pytest.raises(BundleError, match="never overwritten"):
        install_bundle(res["archive"], dst)
    assert json.loads((dst / "experiments/live/exp_a/results.json").read_text()) == {"tampered": True}
    assert not (dst / "lake").exists()  # nothing partially installed


def test_path_traversal_entry_is_rejected(tmp_path: Path) -> None:
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "x"
    payload.write_text("x")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="../escape.txt")
    with pytest.raises(BundleError, match="unsafe"):
        install_bundle(str(evil), tmp_path / "dst")


def test_only_https_urls(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="https"):
        install_bundle("http://example.org/b.tar.gz", tmp_path / "dst")


def test_run_manifest_records_code_provenance() -> None:
    from market_almanac.experiments.runner import code_provenance

    prov = code_provenance()
    assert set(prov) == {"git_commit", "dirty"}
    if prov["git_commit"] is not None:  # running from a git checkout
        assert len(prov["git_commit"]) == 40 and isinstance(prov["dirty"], bool)
