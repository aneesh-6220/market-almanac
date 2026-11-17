"""Provider B: NASA POWER daily point API.

Verified against https://power.larc.nasa.gov/docs/services/api/temporal/daily/ and a live
response (API v2.10.x):

* ``GET /api/temporal/daily/point?parameters=...&community=AG&latitude=..&longitude=..
  &start=YYYYMMDD&end=YYYYMMDD&format=JSON&time-standard=UTC|LST``
* Units: PRECTOTCORR mm/day, T2M/T2M_MAX/T2M_MIN °C. Fill value: -999 (``header.fill_value``).
* Daily data from 1981-01-01 to near real time; max 20 parameters per point request.
* The daily API *defaults to LST*; ShockTrace always sets the time standard explicitly.

SCIENTIFIC RESTRICTION: weather at the coordinates of a retail market is a *geographic
proxy*. It is not the weather in the areas where the traded commodity was grown.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from shocktrace.data.identity import power_grid_cell, weather_location_id
from shocktrace.data.schema import WEATHER_MONTHLY, coerce
from shocktrace.data.weather import aggregate_daily_to_monthly
from shocktrace.http import HttpClient
from shocktrace.providers.base import (
    AuthKind,
    DatasetSpec,
    FetchResult,
    Provider,
    ProviderInfo,
    ProviderSchemaError,
    utcnow,
)

BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = ("PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN")
EXPECTED_UNITS = {"PRECTOTCORR": "mm/day", "T2M": "C", "T2M_MAX": "C", "T2M_MIN": "C"}
EARLIEST = date(1981, 1, 1)
SPATIAL_BASIS = "market-local geographic proxy (POWER grid cell containing the market)"


class NasaPowerProvider(Provider):
    info = ProviderInfo(
        id="nasa_power",
        name="NASA POWER (daily)",
        description="NASA Prediction Of Worldwide Energy Resources daily meteorology (MERRA-2 based) by point.",
        homepage="https://power.larc.nasa.gov/",
        docs_url="https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        license="NASA open data; no usage restrictions. Acknowledge NASA POWER per its citation guidance.",
        attribution=(
            "Data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded "
            "through the NASA Earth Science/Applied Science Program."
        ),
        auth=AuthKind.NONE,
        auth_env_vars=(),
        datasets=(
            DatasetSpec(
                "weather_monthly",
                "Monthly aggregates of daily precipitation and temperature",
                "monthly (from daily)",
                "0.5° x 0.625° grid cell",
                PARAMETERS,
                "weather_monthly",
            ),
        ),
        capabilities=("point_timeseries", "explicit_time_standard", "monthly_aggregation", "grid_dedup", "cache"),
        caveats=(
            "Market-local weather is a geographic proxy, not verified crop-production exposure.",
            "Coarse (~50 km) reanalysis-based grid; local rainfall can differ substantially.",
        ),
    )

    def __init__(self, http: HttpClient, time_standard: str = "UTC") -> None:
        super().__init__(http)
        if time_standard not in ("UTC", "LST"):
            raise ValueError("time_standard must be 'UTC' or 'LST'")
        self.time_standard = time_standard

    def is_configured(self) -> bool:
        return True

    async def _probe(self) -> str:
        payload = await self._request(0.25, 0.3125, date(2020, 1, 1), date(2020, 1, 2), use_cache=False)
        parse_power_daily(payload)
        return "daily point endpoint responded"

    async def _request(self, lat: float, lon: float, start: date, end: date, use_cache: bool = True) -> Any:
        return await self.http.get_json(
            BASE_URL,
            params={
                "parameters": ",".join(PARAMETERS),
                "community": "AG",
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "start": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "format": "JSON",
                "time-standard": self.time_standard,
            },
            use_cache=use_cache,
        )

    async def fetch(self, dataset: str, **params: Any) -> FetchResult:
        self.dataset_spec(dataset)
        lat, lon = float(params["lat"]), float(params["lon"])
        start: date = params.get("start") or EARLIEST
        end: date = params.get("end") or date.today()
        if start < EARLIEST:
            raise ValueError(f"NASA POWER daily data begin {EARLIEST.isoformat()}")
        if end < start:
            raise ValueError("end must not be before start")
        clat, clon = power_grid_cell(lat, lon)
        before = self.http.request_count
        payload = await self._request(clat, clon, start, end, use_cache=params.get("use_cache", True))
        daily, meta = parse_power_daily(payload)
        monthly = aggregate_daily_to_monthly(daily)
        monthly["location_id"] = weather_location_id(lat, lon)
        monthly["provider"] = "nasa_power"
        monthly["lat"], monthly["lon"] = clat, clon
        monthly["time_standard"] = meta["time_standard"]
        monthly["spatial_basis"] = SPATIAL_BASIS
        monthly["retrieved_at"] = utcnow()
        frame = coerce(monthly, WEATHER_MONTHLY)
        return FetchResult(
            provider_id=self.id,
            dataset=dataset,
            frame=frame,
            fetched_at=utcnow(),
            params={
                "lat": lat,
                "lon": lon,
                "grid_lat": clat,
                "grid_lon": clon,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "time_standard": self.time_standard,
            },
            source_urls=[BASE_URL],
            warnings=meta["warnings"],
            raw_record_count=len(daily),
            requests_made=self.http.request_count - before,
            extra={"daily": daily, "api_version": meta["api_version"]},
        )


def parse_power_daily(payload: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse a POWER daily JSON payload into a daily frame with NaN for fill values."""
    try:
        header = payload["header"]
        param_values = payload["properties"]["parameter"]
        param_meta = payload["parameters"]
    except (KeyError, TypeError) as exc:
        raise ProviderSchemaError(f"nasa_power: unexpected payload structure ({exc})") from exc
    fill = header.get("fill_value", -999.0)
    warnings: list[str] = []
    for p in PARAMETERS:
        if p not in param_values:
            raise ProviderSchemaError(f"nasa_power: parameter {p} missing from response")
        unit = param_meta.get(p, {}).get("units")
        if unit != EXPECTED_UNITS[p]:
            raise ProviderSchemaError(f"nasa_power: unexpected unit for {p}: {unit!r}")
    dates = sorted(param_values[PARAMETERS[0]].keys())
    data: dict[str, Any] = {"date": pd.to_datetime(dates, format="%Y%m%d")}
    n_fill = 0
    for p in PARAMETERS:
        vals = np.array([param_values[p].get(d, fill) for d in dates], dtype="float64")
        mask = np.isclose(vals, fill) | (vals <= -998)
        n_fill += int(mask.sum())
        vals[mask] = np.nan
        data[p] = vals
    if n_fill:
        warnings.append(f"{n_fill} fill-value ({fill}) observations converted to missing")
    meta = {
        "time_standard": header.get("time_standard", "unknown"),
        "api_version": header.get("api", {}).get("version"),
        "sources": header.get("sources"),
        "warnings": warnings,
    }
    return pd.DataFrame(data), meta
