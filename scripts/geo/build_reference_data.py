"""Rebuild the reference data committed under packages/shocktrace/src/shocktrace/geo/data/.

Inputs are downloaded once into the git-ignored cache and verified against recorded checksums:

* MapSPAM 2010 v2.0 harvested area (Harvard Dataverse, CC BY 4.0)  -> crop_weights_spam2010.csv
* World Bank "Crop calendar for Africa" (CC BY 4.0)                 -> crop_calendar.yaml

Usage: uv run python scripts/geo/build_reference_data.py [--countries BFA MLI NER]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from shocktrace.geo import spam

CACHE = Path("data/cache")
OUT = Path("packages/shocktrace/src/shocktrace/geo/data")
CAL_URL = "https://datacatalogfiles.worldbank.org/ddh-published/0066842/DR0095318/crop_calendar_gaul0.csv"
CAL_SHA256 = "4aec81e67dd8db2fc95e56d25f9031d9692421d8226519ca773449dbb442b147"
CAL_NAMES = {"Burkina Faso": "BFA", "Mali": "MLI", "Niger": "NER"}
CAL_CROPS = {"Maize": "maize", "Millet": "millet", "Sorghum": "sorghum", "Cowpea": "cowpea"}


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with httpx.stream("GET", url, timeout=1800, follow_redirects=True) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
    return dest


def _digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_weights(countries: list[str]) -> None:
    archive = _download(
        f"https://dataverse.harvard.edu/api/access/datafile/{spam.ARCHIVE_DATAFILE_ID}",
        CACHE / "mapspam" / spam.ARCHIVE_NAME,
    )
    if _digest(archive, "md5") != spam.ARCHIVE_MD5:
        raise SystemExit("MapSPAM archive checksum mismatch: the source file changed; review before use")
    member = CACHE / "mapspam" / spam.MEMBER_NAME
    if not member.exists():
        with zipfile.ZipFile(archive) as z:
            z.extract(spam.MEMBER_NAME, CACHE / "mapspam")
    weights, summaries = spam.build_weights(member, countries)
    weights = weights.drop(columns=["source", "source_license"]).round({"area_ha": 1, "weight": 10})
    header = (
        f"# Crop-production weights on the NASA POWER grid, derived from {spam.SOURCE_CITATION}\n"
        f"# Source licence: {spam.SOURCE_LICENSE}. Source file {spam.ARCHIVE_NAME} (md5 {spam.ARCHIVE_MD5}), member "
        f"{spam.MEMBER_NAME} (harvested area, all technologies, 2009-2011 average).\n"
        f"# Method: shocktrace.geo.spam.cell_weights; cells holding the top {spam.COVERAGE_TARGET:.0%} of national "
        "harvested area, renormalised to sum to 1 per country and crop.\n"
        f"# Built {datetime.now(UTC):%Y-%m-%d} for {', '.join(countries)} by scripts/geo/build_reference_data.py\n"
    )
    buf = io.StringIO()
    weights.to_csv(buf, index=False, lineterminator="\n")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crop_weights_spam2010.csv").write_text(header + buf.getvalue())
    for s in summaries:
        print(f"{s.country_iso3} {s.crop:8s} area {s.total_area_ha:>12,.0f} ha  cells {s.cells_kept}/{s.cells_total}")


def build_calendar() -> None:
    src = _download(CAL_URL, CACHE / "crop_calendar" / "crop_calendar_gaul0.csv")
    if _digest(src, "sha256") != CAL_SHA256:
        raise SystemExit("crop calendar checksum mismatch: the source file changed; review before use")
    entries = []
    for r in csv.DictReader(src.open(encoding="utf-8-sig"), delimiter=";"):
        iso, crop = CAL_NAMES.get(r["name0_shr"]), CAL_CROPS.get(r["crop_name"])
        if iso and crop:
            entries.append(
                {
                    "country_iso3": iso,
                    "crop": crop,
                    "sos_s": int(r["sos_s"]),
                    "sos_e": int(r["sos_e"]),
                    "eos_s": int(r["eos_s"]),
                    "eos_e": int(r["eos_e"]),
                }
            )
    entries.sort(key=lambda e: (e["country_iso3"], e["crop"]))
    doc = {
        "source": {
            "title": "Crop calendar for Africa (national level), World Bank Data Catalog dataset 0066842",
            "url": CAL_URL,
            "sha256": CAL_SHA256,
            "license": "CC BY 4.0",
            "origin": "Dimou, M. (2018). Crop calendar dataset compatible with satellite-derived land surface "
            "phenology. European Commission, Joint Research Centre. http://data.europa.eu/89h/jrc-10112-10003",
            "retrieved": "2026-11-16",
        },
        "units": "dekads 1-36 (three per calendar month): sos = planting window, eos = harvest window",
        "entries": entries,
    }
    (OUT / "crop_calendar.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, width=110))
    print(f"calendar entries: {len(entries)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["BFA", "MLI", "NER"])
    a = ap.parse_args()
    build_weights(a.countries)
    build_calendar()
