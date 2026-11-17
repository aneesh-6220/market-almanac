"""Crop calendars: when each crop's growing season runs, by country.

Source (retrieved 2026-11-16): World Bank Data Catalog, "Crop calendar for Africa" (dataset
0066842, file ``crop_calendar_gaul0.csv``), licence CC BY 4.0, derived from Dimou, M. (2018),
*Crop calendar dataset compatible with satellite-derived land surface phenology*, European
Commission Joint Research Centre, http://data.europa.eu/89h/jrc-10112-10003.

The source gives four dekads (1-36; three per month) per country and crop:

    sos_s .. sos_e   planting window        eos_s .. eos_e   harvest window

Conventions used here (fixed before any model was estimated):

* dekad d falls in calendar month ``(d - 1) // 3 + 1``;
* the *growing season* is every calendar month that contains a dekad from the start of planting
  to the start of harvest, ``sos_s .. eos_s``;
* the *harvest end month* is the month containing ``eos_e``.

Where the source has no national entry for a crop (cowpea in Burkina Faso and Mali), the
country's millet calendar is used, because cowpea is predominantly intercropped with millet and
sorghum in the Sahel; such entries are marked ``basis: fallback``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PACKAGED_CALENDAR = Path(__file__).parent / "data" / "crop_calendar.yaml"
FALLBACK_CROP = {"cowpea": "millet"}


def dekad_month(d: int) -> int:
    if not 1 <= d <= 36:
        raise ValueError("dekad must be in 1..36")
    return (d - 1) // 3 + 1


@dataclass(frozen=True)
class CropSeason:
    country_iso3: str
    crop: str
    sos_s: int
    sos_e: int
    eos_s: int
    eos_e: int
    basis: str = "source"

    @property
    def season_months(self) -> tuple[int, ...]:
        """Calendar months of the growing season, in chronological order (may wrap the year end)."""
        start, end = dekad_month(self.sos_s), dekad_month(self.eos_s)
        n = (end - start) % 12 + 1
        return tuple((start - 1 + i) % 12 + 1 for i in range(n))

    @property
    def start_month(self) -> int:
        return self.season_months[0]

    @property
    def end_month(self) -> int:
        return self.season_months[-1]

    @property
    def harvest_end_month(self) -> int:
        return dekad_month(self.eos_e)

    @property
    def wraps_year(self) -> bool:
        return self.end_month < self.start_month


@lru_cache(maxsize=1)
def load_calendar(path: Path = PACKAGED_CALENDAR) -> dict[tuple[str, str], CropSeason]:
    doc = yaml.safe_load(Path(path).read_text())
    out: dict[tuple[str, str], CropSeason] = {}
    for e in doc["entries"]:
        s = CropSeason(
            e["country_iso3"], e["crop"], e["sos_s"], e["sos_e"], e["eos_s"], e["eos_e"], e.get("basis", "source")
        )
        for d in (s.sos_s, s.sos_e, s.eos_s, s.eos_e):
            dekad_month(d)
        out[(s.country_iso3, s.crop)] = s
    return out


def season_for(country_iso3: str, crop: str) -> CropSeason | None:
    """Season for a crop in a country, using the documented fallback when the source has no entry."""
    cal = load_calendar()
    hit = cal.get((country_iso3, crop))
    if hit is not None:
        return hit
    alt = FALLBACK_CROP.get(crop)
    base = cal.get((country_iso3, alt)) if alt else None
    if base is None:
        return None
    return CropSeason(country_iso3, crop, base.sos_s, base.sos_e, base.eos_s, base.eos_e, basis="fallback")
