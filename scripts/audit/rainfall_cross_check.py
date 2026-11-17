"""Independent cross-check of the NASA POWER rainfall value of 2025-12-02 near Banfora/Niangoloko.

The 2026-11-16 audit found PRECTOTCORR = 276.54 mm/day on 2025-12-02 at the POWER cell centred
10.75 N, -4.6875 E and attributed it to a near-real-time (GEOS-IT) artefact. This script tests
that explanation instead of assuming it:

1. re-queries POWER for the cell and its eight neighbours (live vintage, source header recorded);
2. queries POWER's IMERG precipitation for the same cell (UTC day);
3. samples CHIRPS v3.0 (an independent gauge/satellite product) over the same 0.5 x 0.625 degree box.

Nothing here is used by the production pipeline. Requires the optional ``geo`` dependency group
(``uv sync --group geo``) and network access. CHIRPS files are cached under data/cache/chirps.

Usage: uv run --group geo python scripts/audit/rainfall_cross_check.py [--out docs/audits/evidence/...json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np

LAT, LON = 10.75, -4.6875
DLAT, DLON = 0.5, 0.625
DAY = "2025-12-02"
POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
CHIRPS = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0"
CACHE = Path("data/cache/chirps")


def power(lat: float, lon: float, params: str, start: str, end: str, time_standard: str = "LST") -> dict:
    r = httpx.get(
        POWER,
        params={
            "parameters": params,
            "community": "AG",
            "latitude": lat,
            "longitude": lon,
            "start": start,
            "end": end,
            "format": "JSON",
            "time-standard": time_standard,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def chirps_file(rel: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / Path(rel).name
    if not p.exists():
        with httpx.stream("GET", f"{CHIRPS}/{rel}", timeout=300) as r:
            r.raise_for_status()
            with p.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
    return p


def box_stats(path: Path) -> dict[str, float | int | str]:
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            raise ValueError(f"{path.name}: expected EPSG:4326, got {ds.crs}")
        win = from_bounds(LON - DLON / 2, LAT - DLAT / 2, LON + DLON / 2, LAT + DLAT / 2, ds.transform)
        a = ds.read(1, window=win).astype(float)
        nodata = ds.nodata
    if nodata is not None:
        a[a == nodata] = np.nan
    a[a < 0] = np.nan
    return {
        "file": path.name,
        "pixels": int(np.isfinite(a).sum()),
        "mean_mm": round(float(np.nanmean(a)), 3),
        "max_mm": round(float(np.nanmax(a)), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("docs/audits/evidence/rainfall_2025_12_02.json"))
    args = ap.parse_args()
    key = DAY.replace("-", "")
    out: dict = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cell": {"lat": LAT, "lon": LON, "dlat": DLAT, "dlon": DLON},
        "day": DAY,
    }

    centre = power(LAT, LON, "PRECTOTCORR", "20251125", "20251210")
    out["power_centre"] = {
        "sources": centre["header"]["sources"],
        "api_version": centre["header"]["api"]["version"],
        "daily_mm": centre["properties"]["parameter"]["PRECTOTCORR"],
    }
    neigh = {}
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            la, lo = LAT + di * DLAT, LON + dj * DLON
            d = power(la, lo, "PRECTOTCORR", key, key)
            neigh[f"{la:.2f},{lo:.4f}"] = d["properties"]["parameter"]["PRECTOTCORR"][key]
    out["power_neighbours_mm"] = neigh
    imerg = power(LAT, LON, "IMERG_PRECTOT", "20251130", "20251204", time_standard="UTC")
    out["power_imerg_utc_mm"] = imerg["properties"]["parameter"].get("IMERG_PRECTOT")

    out["chirps_v3"] = {
        "daily_rnl": [
            box_stats(chirps_file(f"daily/final/rnl/2025/chirps-v3.0.rnl.2025.12.{d}.tif")) for d in ("01", "02", "03")
        ],
        "daily_sat_dec02": box_stats(chirps_file("daily/final/sat/2025/chirps-v3.0.sat.2025.12.02.tif")),
        "monthly_dec_2025": box_stats(chirps_file("monthly/africa/tifs/chirps-v3.0.2025.12.tif")),
    }

    others = [v for k, v in neigh.items() if k != f"{LAT:.2f},{LON:.4f}"]
    out["summary"] = {
        "power_centre_mm": neigh[f"{LAT:.2f},{LON:.4f}"],
        "power_neighbour_max_mm": max(others),
        "power_neighbour_median_mm": float(np.median(others)),
        "chirps_rnl_box_mean_mm": out["chirps_v3"]["daily_rnl"][1]["mean_mm"],
        "chirps_sat_box_mean_mm": out["chirps_v3"]["daily_sat_dec02"]["mean_mm"],
        "chirps_month_box_mean_mm": out["chirps_v3"]["monthly_dec_2025"]["mean_mm"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    print(json.dumps(out["summary"], indent=1))
    print("POWER source header:", out["power_centre"]["sources"])
    print("POWER neighbours (mm):", json.dumps(neigh))
    print("POWER IMERG (UTC):", out["power_imerg_utc_mm"])
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
