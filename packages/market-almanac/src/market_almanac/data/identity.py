"""Stable identifiers.

A *price series* is identified by the full observation identity – never by commodity
name alone. Two records labelled "Maize" with different units, price types, currencies
or price flags are different series and are never merged.
"""

from __future__ import annotations

import hashlib
import math

SERIES_IDENTITY_FIELDS = (
    "provider",
    "country_iso3",
    "market_code",
    "commodity_code",
    "unit",
    "price_type",
    "price_flag",
    "currency",
)


def _norm(v: object) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip().lower()


def series_id(**identity: object) -> str:
    missing = [f for f in SERIES_IDENTITY_FIELDS if f not in identity]
    if missing:
        raise ValueError(f"series identity missing fields: {missing}")
    raw = "|".join(_norm(identity[f]) for f in SERIES_IDENTITY_FIELDS)
    return "ps_" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def market_id(provider: str, country_iso3: str, market_code: str) -> str:
    return f"{provider}:{country_iso3.upper()}:{market_code}"


def commodity_id(provider: str, commodity_code: str) -> str:
    return f"{provider}:{commodity_code}"


# NASA POWER MERRA-2-based meteorology is provided on a 0.5° x 0.625° grid.
POWER_LAT_STEP = 0.5
POWER_LON_STEP = 0.625


def power_grid_cell(lat: float, lon: float) -> tuple[float, float]:
    """Snap coordinates to the centre of the enclosing POWER meteorology grid cell.

    Markets in the same cell receive identical data, so requests are de-duplicated.
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"invalid coordinates: {lat}, {lon}")
    clat = math.floor(lat / POWER_LAT_STEP) * POWER_LAT_STEP + POWER_LAT_STEP / 2
    clon = math.floor(lon / POWER_LON_STEP) * POWER_LON_STEP + POWER_LON_STEP / 2
    return round(min(clat, 89.75), 4), round(min(clon, 179.6875), 4)


def weather_location_id(lat: float, lon: float) -> str:
    clat, clon = power_grid_cell(lat, lon)
    return f"wx_{clat:.4f}_{clon:.4f}"
