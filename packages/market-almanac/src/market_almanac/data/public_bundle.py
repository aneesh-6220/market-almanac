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

BUNDLE_FORMAT = "market-almanac-public-bundle-1"
PRICES_BUNDLE_FORMAT = "market-almanac-global-prices-1"
CONTEXT_BUNDLE_FORMAT = "market-almanac-economic-context-1"
SUPPORTED_FORMATS = (BUNDLE_FORMAT, PRICES_BUNDLE_FORMAT, CONTEXT_BUNDLE_FORMAT)
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


def prices_bundle_files(data_dir: Path, mode: str) -> Iterator[Path]:
    """Files of the data-only price artefact: the newest partition of every country, its catalog and the
    precomputed price-shock episodes (the Price Shock Investigator's discovery table, ~10 MB).

    Nothing else is needed to serve price browsing: no weather, macro, agriculture, experiments or
    older snapshots, which is why this is ~30 MB where the full research bundle is 75 MB and the Atlas
    reproducibility package 242 MB.
    """
    from market_almanac.globaldata.partitions import PartitionStore
    from market_almanac.globaldata.prices import GLOBAL_CATALOG, GLOBAL_CATALOG_MANIFEST
    from market_almanac.globaldata.shocks import SHOCK_CATALOG, SHOCK_MANIFEST

    store = PartitionStore(data_dir / "lake" / mode, mode)
    for c in store.countries("prices"):
        m = store.latest("prices", c)
        if m is None:
            continue
        d = store.path("prices", c, m.snapshot_id).parent
        yield from sorted(p.relative_to(data_dir) for p in d.iterdir() if p.is_file())
    for name in (GLOBAL_CATALOG, GLOBAL_CATALOG_MANIFEST, SHOCK_CATALOG, SHOCK_MANIFEST):
        if (data_dir / "public" / mode / name).is_file():
            yield Path("public") / mode / name


def _write_bundle(
    data_dir: Path, files: list[Path], mode: str, out_dir: Path, *, fmt: str, prefix: str, extra: dict[str, Any]
) -> dict[str, Any]:
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
        "format": fmt,
        "mode": mode,
        "created_at": created.isoformat(),
        "code_commit": _git_commit(),
        "n_files": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "attribution": ATTRIBUTION,
        **extra,
        "files": entries,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}-{mode}-{created.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
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
    return {
        "archive": str(archive),
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "n_files": len(entries),
        "total_bytes": manifest["total_bytes"],
    }


def build_bundle(data_dir: Path, mode: str, out_dir: Path) -> dict[str, Any]:
    """Write ``market-almanac-<mode>-data-<stamp>.tar.gz`` and its ``.sha256`` to ``out_dir``."""
    data_dir = Path(data_dir)
    files = list(bundle_files(data_dir, mode))
    if not any(str(f).startswith(f"lake/{mode}/") for f in files):
        raise BundleError(f"no lake snapshots for mode {mode!r} under {data_dir}; ingest data first")
    return _write_bundle(
        data_dir,
        files,
        mode,
        out_dir,
        fmt=BUNDLE_FORMAT,
        prefix="market-almanac",
        extra={"excluded": "HTTP cache, raw provider downloads, feature matrices, databases and credentials"},
    )


def build_prices_bundle(data_dir: Path, mode: str, out_dir: Path) -> dict[str, Any]:
    """Write ``market-almanac-global-prices-<mode>-<stamp>.tar.gz``: the data-only price artefact."""
    import pandas as pd

    from market_almanac.globaldata.prices import GLOBAL_CATALOG, GLOBAL_CATALOG_MANIFEST

    data_dir = Path(data_dir)
    files = list(prices_bundle_files(data_dir, mode))
    names = {f.name for f in files}
    if not {GLOBAL_CATALOG, GLOBAL_CATALOG_MANIFEST} <= names or not any(
        "partitions/prices" in f.as_posix() for f in files
    ):
        raise BundleError("price partitions and the global catalog are required; run `market-almanac global catalog`")
    cat_manifest = json.loads((data_dir / "public" / mode / GLOBAL_CATALOG_MANIFEST).read_text())
    snaps = {f.parts[-2] for f in files if f.name == "manifest.json" and "partitions" in f.parts}
    built = {c: v["snapshot_id"] for c, v in cat_manifest["countries"].items()}
    in_bundle = {f.parts[-3]: f.parts[-2] for f in files if f.name == "data.parquet" and "partitions" in f.parts}
    if in_bundle != built:
        raise BundleError("the catalog was built from different snapshots than the newest partitions; rebuild it")
    from market_almanac.globaldata.shocks import SHOCK_CATALOG, SHOCK_MANIFEST, load_manifest, stale_countries

    if not {SHOCK_CATALOG, SHOCK_MANIFEST} <= names:
        raise BundleError("the price-shock catalog is required; run `market-almanac global shocks`")
    shock_manifest = load_manifest(data_dir / "public" / mode) or {}
    if stale_countries(shock_manifest, in_bundle) or set(shock_manifest.get("countries", {})) != set(in_bundle):
        raise BundleError(
            "the price-shock catalog was built from different snapshots; rerun `market-almanac global shocks`"
        )
    rows = sum(
        int(pd.read_parquet(data_dir / f, columns=["series_id"]).shape[0]) for f in files if f.name == "data.parquet"
    )
    res = _write_bundle(
        data_dir,
        files,
        mode,
        out_dir,
        fmt=PRICES_BUNDLE_FORMAT,
        prefix="market-almanac-global-prices",
        extra={
            "countries": len(in_bundle),
            "observations": rows,
            "snapshots": dict(sorted(in_bundle.items())),
            "excluded": "weather, macro, agriculture, experiments, studies, older snapshots, caches, credentials",
            # this artefact holds WFP prices and nothing else, so it names only that source (and what was changed)
            "attribution": [
                ATTRIBUTION[0],
                "Licence: CC BY-IGO 3.0 (https://creativecommons.org/licenses/by/3.0/igo/). The licence notice and "
                "this attribution must be kept when the data are redistributed.",
            ],
            "adaptation_notice": (
                "Adapted material. The price partitions are normalised copies of WFP's monthly records (one record per "
                "market, commodity, unit, price type, currency and month); global_series_catalog.parquet and "
                "shock_catalog.parquet are statistics computed from them by Market Almanac. WFP, HDX and OCHA have not "
                "reviewed or endorsed them."
            ),
        },
    )
    res.update(countries=len(in_bundle), observations=rows, partitions=len(snaps))
    return res


def _fetch(source: str, dest: Path) -> Path:
    if source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": "market-almanac-bundle-installer"})
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
        if manifest.get("format") not in SUPPORTED_FORMATS:
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
        marker = {
            BUNDLE_FORMAT: "installed",
            PRICES_BUNDLE_FORMAT: "global-prices-installed",
            CONTEXT_BUNDLE_FORMAT: "context-installed",
        }[manifest["format"]]
        (record / f"{manifest['mode']}-{marker}.json").write_text(
            json.dumps({k: v for k, v in manifest.items() if k != "files"} | {"archive_sha256": digest}, indent=1)
        )
    return {
        "mode": manifest["mode"],
        "format": manifest["format"],
        "archive_sha256": digest,
        "files": len(listed),
        "written": written,
        "already_present": len(listed) - written,
    }
