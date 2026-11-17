"""Versioned, hash-verified public data bundle.

A deployed API, or someone who has just cloned the repository, needs the same read-only files the
analysis was run on: the Parquet lake snapshots, the materialised public catalog and the
experiment artefacts (results and per-forecast predictions). Those live under ``data/``, which is
not version-controlled. A *public data bundle* packages exactly those files into one
``.tar.gz`` with a manifest that records every file's SHA-256, so the files can be published (for
example as a release asset), installed anywhere and verified byte for byte.

What is included, per mode:

- ``lake/<mode>/**``: every snapshot (data + manifest). Snapshots are immutable and named by id.
- ``public/<mode>/**``: the series catalog and coverage inventory.
- ``experiments/<mode>/<id>/``: ``results.json``, ``predictions.parquet``, ``config.json`` and
  ``manifest.json`` of every run, superseded runs included (lineage is history, not clutter);
  ``studies/**``. Feature matrices are left out: they are reproducible from the lake and the
  config and no public endpoint reads them.

What is never included: the HTTP cache, raw provider downloads (MapSPAM, CHIRPS, FAOSTAT bulk
files), databases, ``.env`` or any credential. Installing never overwrites a file whose content
differs from the bundle, because snapshots and experiment artefacts are immutable.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

BUNDLE_FORMAT = "shocktrace-public-bundle-1"
MANIFEST_NAME = "BUNDLE_MANIFEST.json"
EXPERIMENT_FILES = ("results.json", "predictions.parquet", "config.json", "manifest.json")
MAX_DOWNLOAD_BYTES = 2 * 1024**3

ATTRIBUTION = [
    "Food prices: World Food Programme (WFP), via the Humanitarian Data Exchange HAPI. WFP data: CC BY-IGO 3.0; "
    "HDX terms of service apply.",
    "Weather: NASA POWER (Prediction Of Worldwide Energy Resources), NASA Langley Research Center. Public; cite "
    "NASA POWER.",
    "Development indicators: World Bank World Development Indicators, CC BY 4.0.",
    "Consumer prices and exchange rates: International Monetary Fund, used under the IMF copyright and usage terms.",
    "Agricultural statistics: FAOSTAT, Food and Agriculture Organization of the United Nations, CC BY 4.0.",
    "Crop-area weights (derived, inside experiment results): IFPRI MapSPAM 2010, CC BY 4.0. Crop calendars: "
    "World Bank / JRC Africa crop calendar.",
]


class BundleError(RuntimeError):
    """The bundle is malformed, does not verify, or conflicts with installed data."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def bundle_files(data_dir: Path, mode: str) -> Iterator[Path]:
    """Yield the files (relative to ``data_dir``) that belong in the bundle for ``mode``."""
    for sub in (Path("lake") / mode, Path("public") / mode):
        root = data_dir / sub
        if root.exists():
            yield from sorted(p.relative_to(data_dir) for p in root.rglob("*") if p.is_file())
    exp_root = data_dir / "experiments" / mode
    if exp_root.exists():
        for d in sorted(p for p in exp_root.iterdir() if p.is_dir()):
            if d.name == "studies":
                yield from sorted(p.relative_to(data_dir) for p in d.rglob("*") if p.is_file())
                continue
            for name in EXPERIMENT_FILES:
                if (d / name).is_file():
                    yield (d / name).relative_to(data_dir)


def build_bundle(data_dir: Path, mode: str, out_dir: Path) -> dict[str, Any]:
    """Write ``shocktrace-<mode>-data-<stamp>.tar.gz`` and its ``.sha256`` to ``out_dir``."""
    data_dir = Path(data_dir)
    files = list(bundle_files(data_dir, mode))
    if not any(str(f).startswith(f"lake/{mode}/") for f in files):
        raise BundleError(f"no lake snapshots for mode {mode!r} under {data_dir}; ingest data first")
    entries: list[dict[str, Any]] = [
        {
            "path": PurePosixPath(*f.parts).as_posix(),
            "bytes": (data_dir / f).stat().st_size,
            "sha256": _sha256(data_dir / f),
        }
        for f in files
    ]
    created = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "format": BUNDLE_FORMAT,
        "mode": mode,
        "created_at": created.isoformat(),
        "code_commit": _git_commit(),
        "n_files": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "attribution": ATTRIBUTION,
        "excluded": "HTTP cache, raw provider downloads, feature matrices, databases and credentials",
        "files": entries,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"shocktrace-{mode}-data-{created.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    archive = out_dir / name
    with tarfile.open(archive, "w:gz") as tar:
        blob = json.dumps(manifest, indent=1).encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size, info.mtime = len(blob), int(created.timestamp())
        tar.addfile(info, io.BytesIO(blob))
        for f in files:
            tar.add(data_dir / f, arcname=PurePosixPath(*f.parts).as_posix(), recursive=False)
    digest = _sha256(archive)
    (out_dir / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    return {"archive": str(archive), "sha256": digest, "n_files": len(entries), "total_bytes": manifest["total_bytes"]}


def _fetch(source: str, dest: Path) -> Path:
    if source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": "shocktrace-bundle-installer"})
        with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as f:
            n = 0
            while chunk := r.read(1 << 20):
                n += len(chunk)
                if n > MAX_DOWNLOAD_BYTES:
                    raise BundleError("download exceeds the 2 GiB bundle limit")
                f.write(chunk)
        return dest
    if "://" in source:
        raise BundleError("only https:// URLs or local paths are accepted")
    return Path(source)


def _safe_member(member: tarfile.TarInfo) -> PurePosixPath:
    p = PurePosixPath(member.name)
    if p.is_absolute() or ".." in p.parts or not (member.isfile() or member.isdir()):
        raise BundleError(f"unsafe entry in bundle: {member.name}")
    return p


def install_bundle(source: str, data_dir: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    """Verify and install a bundle into ``data_dir``. Idempotent; never overwrites differing files."""
    data_dir = Path(data_dir)
    with tempfile.TemporaryDirectory(prefix="st_bundle_") as tmp:
        archive = _fetch(source, Path(tmp) / "bundle.tar.gz")
        if not archive.is_file():
            raise BundleError(f"bundle not found: {source}")
        digest = _sha256(archive)
        if expected_sha256 and digest != expected_sha256.strip().lower():
            raise BundleError(f"archive SHA-256 {digest} does not match the expected {expected_sha256}")
        stage = Path(tmp) / "stage"
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for mem in members:
                _safe_member(mem)
            tar.extractall(stage, members=members, filter="data")
        man_path = stage / MANIFEST_NAME
        if not man_path.is_file():
            raise BundleError("bundle has no manifest")
        manifest = json.loads(man_path.read_text())
        if manifest.get("format") != BUNDLE_FORMAT:
            raise BundleError(f"unsupported bundle format {manifest.get('format')!r}")
        listed = {e["path"]: e for e in manifest["files"]}
        present = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()} - {MANIFEST_NAME}
        if present != set(listed):
            raise BundleError("bundle contents do not match its manifest")
        conflicts: list[str] = []
        for rel, e in listed.items():
            src = stage / rel
            if _sha256(src) != e["sha256"]:
                raise BundleError(f"checksum mismatch for {rel}")
            dst = data_dir / rel
            if dst.exists() and _sha256(dst) != e["sha256"]:
                conflicts.append(rel)
        if conflicts:
            raise BundleError(
                f"{len(conflicts)} installed file(s) differ from the bundle (e.g. {conflicts[0]}); immutable artefacts "
                "are never overwritten. Install into an empty DATA_DIR or remove the conflicting files deliberately."
            )
        written = 0
        for rel in listed:
            dst = data_dir / rel
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp_dst = dst.with_name(dst.name + ".part")
            shutil.copyfile(stage / rel, tmp_dst)
            os.replace(tmp_dst, dst)
            written += 1
        record = data_dir / "bundles"
        record.mkdir(parents=True, exist_ok=True)
        (record / f"{manifest['mode']}-installed.json").write_text(
            json.dumps({k: v for k, v in manifest.items() if k != "files"} | {"archive_sha256": digest}, indent=1)
        )
    return {
        "mode": manifest["mode"],
        "archive_sha256": digest,
        "files": len(listed),
        "written": written,
        "already_present": len(listed) - written,
    }
