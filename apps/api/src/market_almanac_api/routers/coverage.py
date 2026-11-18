"""Global coverage registry endpoints (read-only; serves a small materialized JSON document).

The registry is built offline by ``market-almanac global registry``; this router only reads it,
so the cost of a request is independent of how much data was ingested.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path as FsPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from market_almanac.config import Settings
from market_almanac.globaldata.registry import PACKAGED_REGISTRY, STATUSES, registry_path
from market_almanac_api.deps import settings_dep

router = APIRouter(prefix="/api/v1/coverage", tags=["discovery"])

_LIST_FIELDS = (
    "country_iso3",
    "name",
    "status",
    "price_sources",
    "markets",
    "commodities",
    "series",
    "observations",
    "first_period",
    "last_period",
    "eligible_series",
    "market_coordinate_completeness",
    "forecast_eligible",
    "macro_ingested",
    "agriculture_ingested",
    "last_successful_refresh",
)


class _RegistryCache:
    """Re-read the JSON only when the file changes (mtime), so a rebuilt registry is picked up."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple[str, float] | None = None
        self._doc: dict[str, Any] | None = None

    def get(self, settings: Settings) -> tuple[dict[str, Any], str]:
        p = registry_path(settings)
        source = "materialized"
        if not p.exists():
            if settings.market_almanac_mode.value != "live" or not PACKAGED_REGISTRY.exists():
                raise HTTPException(404, "No coverage registry has been built for this deployment.")
            p, source = FsPath(PACKAGED_REGISTRY), "packaged"
        key = (str(p), p.stat().st_mtime)
        with self._lock:
            if self._key != key:
                self._doc, self._key = json.loads(p.read_text()), key
            assert self._doc is not None
            return self._doc, source


_cache = _RegistryCache()


@router.get("/registry")
def registry(
    s: Annotated[Settings, Depends(settings_dep)],
    status: Annotated[str | None, Query(description="filter by status: " + ", ".join(STATUSES))] = None,
    q: Annotated[str | None, Query(max_length=60, description="case-insensitive name or ISO3 search")] = None,
    observed_only: Annotated[bool, Query(description="only countries with stored observations")] = False,
) -> dict[str, Any]:
    """Per-country coverage status, with counts and the definitions of each status."""
    if status is not None and status not in STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(STATUSES)}")
    doc, source = _cache.get(s)
    rows = doc["countries"]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in str(r["name"]).lower() or ql == r["country_iso3"].lower()]
    if observed_only:
        rows = [r for r in rows if r.get("observations")]
    return {
        "registry_version": doc["registry_version"],
        "generated_at": doc["generated_at"],
        "source": source,
        "status_definitions": doc["status_definitions"],
        "counts": doc["counts"],
        "totals": doc["totals"],
        "discovery": doc["discovery"],
        "countries": [{k: r.get(k) for k in _LIST_FIELDS} for r in rows],
    }


@router.get("/registry/{iso3}")
def registry_country(
    iso3: Annotated[str, Path(pattern=r"^[A-Z]{3}$", description="ISO 3166-1 alpha-3 code")],
    s: Annotated[Settings, Depends(settings_dep)],
) -> dict[str, Any]:
    """Full registry record for one country: QC, environment, snapshot hashes, evaluations, licence."""
    doc, source = _cache.get(s)
    for r in doc["countries"]:
        if r["country_iso3"] == iso3:
            return {**r, "registry_generated_at": doc["generated_at"], "source": source}
    raise HTTPException(404, f"{iso3} is not in the coverage registry")
