"""Crop-production weights from IFPRI MapSPAM 2010 (v2.0), aggregated to the NASA POWER grid.

Source (verified 2026-11-16 against the Harvard Dataverse API):

    International Food Policy Research Institute, 2019. "Global Spatially-Disaggregated Crop
    Production Statistics Data for 2010 Version 2.0", https://doi.org/10.7910/DVN/PRFF8V,
    Harvard Dataverse, V4.  Licence: CC BY 4.0.

File used: ``spam2010v2r0_global_harv_area.csv.zip`` (144.5 MB, MD5 below), member
``spam2010V2r0_global_H_TA.csv``: harvested area in hectares, *all technologies*, one row per
5-arcminute pixel. ``x``/``y`` are the longitude/latitude of the pixel centroid in geographic
coordinates (WGS84); statistics are the 2009-2011 average.

Weights. For crop k and country C, every SPAM pixel labelled ``iso3 = C`` is assigned to the
NASA POWER cell (0.5° latitude x 0.625° longitude) that contains its centroid. With A(k, i) the
harvested area summed over pixels in POWER cell i,

    w(k, i) = A(k, i) / sum_j A(k, j)        (w >= 0, sum_i w = 1)

To bound the number of weather requests, cells are ranked by area and only the smallest set
holding at least ``COVERAGE_TARGET`` (95%) of the national harvested area is kept, then
renormalised; the retained share is recorded.

What the weights are not: they describe where a crop was grown around 2010, nationally. They do
not identify the farms that supply a given market, and they are static (crop geography shifts).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from shocktrace.data.identity import power_grid_cell, weather_location_id

SOURCE_ID = "mapspam_2010_v2r0"
SOURCE_DOI = "https://doi.org/10.7910/DVN/PRFF8V"
SOURCE_LICENSE = "CC BY 4.0"
SOURCE_CITATION = (
    "International Food Policy Research Institute (2019). Global Spatially-Disaggregated Crop Production "
    "Statistics Data for 2010 Version 2.0. Harvard Dataverse, V4. https://doi.org/10.7910/DVN/PRFF8V"
)
ARCHIVE_NAME = "spam2010v2r0_global_harv_area.csv.zip"
ARCHIVE_MD5 = "e45d61cc0694a905c9760cfff6ea66b8"
ARCHIVE_DATAFILE_ID = 3984976  # Dataverse file id; download: /api/access/datafile/<id>
MEMBER_NAME = "spam2010V2r0_global_H_TA.csv"
PIXEL_DEGREES = 1.0 / 12.0  # 5 arcminutes
COVERAGE_TARGET = 0.95

# The 42 SPAM crop codes (ReadMe_v2r0_Global.txt).
SPAM_CROPS = [
    "whea",
    "rice",
    "maiz",
    "barl",
    "pmil",
    "smil",
    "sorg",
    "ocer",
    "pota",
    "swpo",
    "yams",
    "cass",
    "orts",
    "bean",
    "chic",
    "cowp",
    "pige",
    "lent",
    "opul",
    "soyb",
    "grou",
    "cnut",
    "oilp",
    "sunf",
    "rape",
    "sesa",
    "ooil",
    "sugc",
    "sugb",
    "cott",
    "ofib",
    "acof",
    "rcof",
    "coco",
    "teas",
    "toba",
    "bana",
    "plnt",
    "trof",
    "temf",
    "vege",
    "rest",
]

# ShockTrace crop keys -> SPAM codes. Millet is split by SPAM into pearl and small millet; summed.
CROP_SPAM_CODES: dict[str, tuple[str, ...]] = {
    "millet": ("pmil", "smil"),
    "sorghum": ("sorg",),
    "maize": ("maiz",),
    "cowpea": ("cowp",),
}

# WFP commodity names (HDX) -> crop key. Matching is on the name because WFP codes differ between
# countries (sorghum is 135 in Burkina Faso and 65 in Mali/Niger). Rice is deliberately absent:
# imported rice is not grown locally and local rice is largely irrigated.
_NAME_RULES: tuple[tuple[str, str], ...] = (
    (r"^millet\b", "millet"),
    (r"^sorghum\b", "sorghum"),
    (r"^maize\b", "maize"),
    (r"^beans \(ni[eé]b[eé]", "cowpea"),
    (r"^cowpeas?\b", "cowpea"),
)


class CropGeographyError(ValueError):
    """The crop-distribution source failed a structural or plausibility check."""


def crop_for_commodity(commodity_name: str) -> str | None:
    """Crop key for a WFP commodity name, or None when no production-region proxy is defined."""
    name = commodity_name.strip().lower()
    for pattern, crop in _NAME_RULES:
        if re.search(pattern, name):
            return crop
    return None


def validate_crop_codes(crops: dict[str, tuple[str, ...]] | None = None) -> None:
    for crop, codes in (crops or CROP_SPAM_CODES).items():
        bad = [c for c in codes if c not in SPAM_CROPS]
        if bad:
            raise CropGeographyError(f"crop {crop!r} maps to unknown SPAM codes {bad}")


N_LEADING_FIELDS = 9 + len(SPAM_CROPS)  # identification fields + 42 crop columns


def load_spam_pixels(csv_path: Path, iso3: list[str]) -> pd.DataFrame:
    """Read the harvested-area pixels of the given countries and validate their structure.

    The published CSV is not strictly well formed (free-text admin names at the end of a row
    contain unescaped quotes), so rows are selected by their ``"ISO3",`` prefix and only the
    leading identification and crop fields, which never contain commas or quotes inside values,
    are parsed.
    """
    validate_crop_codes()
    prefixes = tuple(f'"{c}",' for c in iso3)
    rows: list[list[str]] = []
    with Path(csv_path).open("r", encoding="latin-1", newline="") as fh:
        header = [h.strip().strip('"').lower() for h in fh.readline().split(",")]
        expected = ["iso3", "prod_level", "alloc_key", "cell5m", "x", "y", "rec_type", "tech_type", "unit"]
        if header[:9] != expected or header[9:N_LEADING_FIELDS] != [f"{c}_a" for c in SPAM_CROPS]:
            raise CropGeographyError("unexpected SPAM column layout (wrong file or version?)")
        for line in fh:
            if line.startswith(prefixes):
                rows.append([v.strip('"') for v in line.split(",", N_LEADING_FIELDS)[:N_LEADING_FIELDS]])
    if not rows:
        raise CropGeographyError(f"no SPAM pixels for {iso3}")
    df = pd.DataFrame(rows, columns=header[:N_LEADING_FIELDS])
    codes = sorted({c for v in CROP_SPAM_CODES.values() for c in v})
    df = df[["iso3", "cell5m", "x", "y", "rec_type", "tech_type", "unit", *[f"{c}_a" for c in codes]]].copy()
    for c in ["x", "y", *[f"{c}_a" for c in codes]]:
        df[c] = pd.to_numeric(df[c], errors="raise")
    if set(df["rec_type"]) != {"H"} or set(df["tech_type"]) != {"A"} or set(df["unit"]) != {"ha"}:
        raise CropGeographyError("expected harvested area (H), all technologies (A), hectares")
    validate_pixel_grid(df)
    area = df[[f"{c}_a" for c in codes]]
    if (area < 0).any().any() or area.isna().any().any():
        raise CropGeographyError("negative or missing harvested area")
    if df.duplicated(["iso3", "cell5m"]).any():
        raise CropGeographyError("duplicate SPAM pixels")
    return df


def validate_pixel_grid(df: pd.DataFrame) -> None:
    """Coordinate-reference check: centroids must lie on the global 5-arcminute lon/lat lattice."""
    x, y = df["x"].to_numpy(float), df["y"].to_numpy(float)
    if (np.abs(x) > 180).any() or (np.abs(y) > 90).any():
        raise CropGeographyError("pixel coordinates are not geographic longitude/latitude")
    for v, origin in ((x, -180.0), (y, -90.0)):
        k = (v - origin) / PIXEL_DEGREES - 0.5  # centroid index on the lattice
        if np.abs(k - np.round(k)).max() > 1e-3:
            raise CropGeographyError("pixel centroids are not on the 5-arcminute lattice")


@dataclass(frozen=True)
class WeightSummary:
    country_iso3: str
    crop: str
    total_area_ha: float
    cells_total: int
    cells_kept: int
    area_share_kept: float


def cell_weights(
    pixels: pd.DataFrame, iso3: str, crop: str, coverage: float = COVERAGE_TARGET
) -> tuple[pd.DataFrame, WeightSummary]:
    """Production weights of one crop in one country on the POWER grid (see module docstring)."""
    if not 0 < coverage <= 1:
        raise ValueError("coverage must be in (0, 1]")
    p = pixels[pixels["iso3"] == iso3]
    area = p[[f"{c}_a" for c in CROP_SPAM_CODES[crop]]].sum(axis=1)
    if p.empty or area.sum() <= 0:
        raise CropGeographyError(f"SPAM reports no {crop} harvested area in {iso3}")
    cells = [power_grid_cell(float(lat), float(lon)) for lat, lon in zip(p["y"], p["x"], strict=True)]
    g = (
        pd.DataFrame({"lat": [c[0] for c in cells], "lon": [c[1] for c in cells], "area_ha": area.to_numpy()})
        .groupby(["lat", "lon"], as_index=False)["area_ha"]
        .sum()
    )
    g = g[g["area_ha"] > 0].sort_values(["area_ha", "lat", "lon"], ascending=[False, True, True])
    total = float(g["area_ha"].sum())
    cum = g["area_ha"].cumsum() / total
    keep = int(np.searchsorted(cum.to_numpy(), coverage - 1e-12) + 1)
    kept = g.iloc[:keep].copy()
    kept["weight"] = kept["area_ha"] / kept["area_ha"].sum()
    kept["location_id"] = [weather_location_id(la, lo) for la, lo in zip(kept["lat"], kept["lon"], strict=True)]
    kept["country_iso3"], kept["crop"] = iso3, crop
    kept["area_share_kept"] = float(kept["area_ha"].sum() / total)
    summary = WeightSummary(iso3, crop, total, len(g), len(kept), float(kept["area_ha"].sum() / total))
    cols = ["country_iso3", "crop", "location_id", "lat", "lon", "area_ha", "weight", "area_share_kept"]
    return kept[cols].reset_index(drop=True), summary


def check_weights(w: pd.DataFrame) -> None:
    """Invariants every weight table must satisfy (also enforced by the tests)."""
    if (w["weight"] < 0).any():
        raise CropGeographyError("negative production weight")
    sums = w.groupby(["country_iso3", "crop"])["weight"].sum()
    if (np.abs(sums - 1) > 1e-9).any():
        raise CropGeographyError("production weights do not sum to 1")
    if w.duplicated(["country_iso3", "crop", "location_id"]).any():
        raise CropGeographyError("duplicate cell in production weights")


def build_weights(
    csv_path: Path, iso3: list[str], crops: list[str] | None = None
) -> tuple[pd.DataFrame, list[WeightSummary]]:
    pixels = load_spam_pixels(csv_path, iso3)
    frames, summaries = [], []
    for c in iso3:
        for crop in crops or list(CROP_SPAM_CODES):
            try:
                w, s = cell_weights(pixels, c, crop)
            except CropGeographyError:
                continue  # crop not grown in this country according to SPAM
            frames.append(w)
            summaries.append(s)
    out = pd.concat(frames, ignore_index=True)
    out["source"], out["source_license"] = SOURCE_ID, SOURCE_LICENSE
    check_weights(out)
    return out, summaries


PACKAGED_WEIGHTS = Path(__file__).parent / "data" / "crop_weights_spam2010.csv"


def packaged_weights() -> pd.DataFrame:
    """Weights committed with the package (derived from SPAM 2010 under CC BY 4.0)."""
    if not PACKAGED_WEIGHTS.exists():
        return pd.DataFrame(
            columns=["country_iso3", "crop", "location_id", "lat", "lon", "area_ha", "weight", "area_share_kept"]
        )
    w = pd.read_csv(PACKAGED_WEIGHTS, comment="#")
    check_weights(w)
    return w
