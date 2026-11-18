"""Audit v1.1, Audit 5: build (or verify) the Forecastability Atlas v1 reproducibility package.

The public v1.0 data bundle (``data-v1.0.0``, built 2026-11-17T12:42Z) predates the global
country-partitioned ingest (2026-11-18T01:52Z) and contains none of the snapshots the atlas
froze, so a fresh clone cannot reproduce the atlas from it. This package contains exactly:

* the 88 pinned input snapshots named in the freeze record (49 WFP price partitions, 39 NASA
  POWER weather partitions) and the pinned research-lake weather snapshot, with their manifests;
* the whole study directory (freeze, spec, results, published summary, SHA256SUMS, RO-Crate,
  primary predictions, and every experiment's config, manifest, results, features, predictions).

The archive is deterministic (sorted members, fixed mtime/uid/gid) and ``PACKAGE_MANIFEST.json``
lists the SHA-256 of every member plus the licence/attribution block (WFP prices via HDX:
CC BY-IGO, licence field read from the HDX CKAN API on 2026-11-18; NASA POWER: public, cite).

    uv run python scripts/audit/build_atlas_package.py build --data data --out dist
    uv run python scripts/audit/build_atlas_package.py verify dist/forecastability-atlas-v1-repro-*.tar.gz

Install into a fresh clone by extracting the archive at the repository root (it only creates
paths under ``data/``); ``verify`` re-hashes every member before you trust it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

STUDY = "forecastability-atlas-v1"
ATTRIBUTION = {
    "wfp_food_prices": {
        "source": "World Food Programme (WFP) market monitoring, via HDX HAPI (Humanitarian Data Exchange)",
        "licence": "CC BY-IGO (Creative Commons Attribution for Intergovernmental Organisations)",
        "licence_checked": "2026-11-18, HDX CKAN package_show?id=global-wfp-food-prices -> license_id cc-by-igo",
        "url": "https://data.humdata.org/dataset/global-wfp-food-prices",
        "modifications": "normalised to the Market Almanac price schema; series identifiers and quality flags added",
    },
    "nasa_power": {
        "source": "NASA Langley Research Center POWER Project (MERRA-2 based daily meteorology)",
        "licence": "public; NASA POWER asks users to cite the POWER project",
        "url": "https://power.larc.nasa.gov/",
        "modifications": (
            "daily values aggregated to calendar months at the containing POWER grid cell; precipitation QC flags"
        ),
    },
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def members(data: Path) -> list[Path]:
    fr = json.loads((data / "studies" / "live" / STUDY / "freeze.json").read_text())
    out: list[Path] = []
    for key, v in sorted(fr["data_snapshots"].items()):
        ds, c = key.split(":")
        d = (
            data / "lake" / "live" / "partitions" / ds / c / v["snapshot_id"]
            if v["layout"] == "partition"
            else data / "lake" / "live" / ds / v["snapshot_id"]
        )
        files = sorted(d.glob("*"))
        if not files:
            raise FileNotFoundError(f"pinned snapshot {key} {v['snapshot_id']} missing under {d}")
        if v["layout"] == "partition" and sha(d / "data.parquet") != v["file_sha256"]:
            raise ValueError(f"pinned snapshot {key} does not match its frozen SHA-256")
        out += files
    out += sorted(
        p for p in (data / "studies" / "live" / STUDY).rglob("*") if p.is_file() and not p.name.endswith(".tmp")
    )
    return out


def build(data: Path, out_dir: Path) -> Path:
    files = members(data)
    root = data.parent
    entries = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": sha(p)} for p in files]
    fr = json.loads((data / "studies" / "live" / STUDY / "freeze.json").read_text())
    manifest = {
        "package": f"{STUDY}-reproducibility",
        "package_version": "1",
        "study": STUDY,
        "spec_hash": fr["spec_hash"],
        "selection_hash": fr["selection_hash"],
        "frozen_at": fr["frozen_at"],
        "attribution": ATTRIBUTION,
        "n_files": len(entries),
        "files": entries,
        "install": (
            "extract at the repository root of a clone; then run the commands in "
            "docs/audits/ATLAS_V1_INDEPENDENT_AUDIT.md"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:12]
    target = out_dir / f"{STUDY}-repro-{digest}.tar.gz"

    def info(name: str, size: int) -> tarfile.TarInfo:
        ti = tarfile.TarInfo(name)
        ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = size, 0, 0o644, 0, 0, "", ""
        return ti

    import gzip

    with (
        open(target, "wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        mb = json.dumps(manifest, indent=1).encode()
        tar.addfile(info("PACKAGE_MANIFEST.json", len(mb)), io.BytesIO(mb))
        for p in files:
            with open(p, "rb") as fh:
                tar.addfile(info(str(p.relative_to(root)), p.stat().st_size), fh)
    (target.parent / (target.name + ".sha256")).write_text(f"{sha(target)}  {target.name}\n")
    print(
        json.dumps(
            {"archive": str(target), "sha256": sha(target), "files": len(entries), "bytes": target.stat().st_size}
        )
    )
    return target


def verify(archive: Path) -> int:
    with tarfile.open(archive, "r:gz") as tar:
        man = json.loads(tar.extractfile("PACKAGE_MANIFEST.json").read())  # type: ignore[union-attr]
        want = {e["path"]: e["sha256"] for e in man["files"]}
        seen, bad = set(), []
        for m in tar.getmembers():
            if m.name == "PACKAGE_MANIFEST.json":
                continue
            if not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts or not m.name.startswith("data/"):
                bad.append(f"unsafe member {m.name}")
                continue
            h = hashlib.sha256(tar.extractfile(m).read()).hexdigest()  # type: ignore[union-attr]
            if want.get(m.name) != h:
                bad.append(f"hash mismatch {m.name}")
            seen.add(m.name)
        missing = set(want) - seen
    print(json.dumps({"files": len(seen), "missing": len(missing), "problems": bad[:10]}))
    return 0 if not bad and not missing else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--data", type=Path, default=Path("data"))
    b.add_argument("--out", type=Path, default=Path("dist"))
    v = sub.add_parser("verify")
    v.add_argument("archive", type=Path)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.data, a.out)
        return 0
    return verify(a.archive)


if __name__ == "__main__":
    sys.exit(main())
