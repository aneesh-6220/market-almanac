"""Economic context: what the installed snapshot holds and which countries it covers.

Reads the installed snapshot only (a local file of about 1 MB, loaded once). It never calls the IMF or the World
Bank and never touches the database; every list is bounded and paged.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from market_almanac.analytics.catalog import iso3_names
from market_almanac.context.coverage import coverage_matrix, coverage_summary
from market_almanac.context.reference import benchmark_table, regimes
from market_almanac_api.deps import economic_context_snapshot

router = APIRouter(prefix="/api/v1/context", tags=["context"])
MAX_PAGE = 100
_COVERAGE: dict[str, Any] = {}


def _clean(v: Any) -> Any:
    import math

    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item"):
        return _clean(v.item())
    return v


@router.get("")
def status() -> dict[str, Any]:
    """Whether economic context is available, its snapshot, source vintages and licence positions."""
    snap, missing = economic_context_snapshot()
    if snap is None:
        return {"available": False, **(missing or {})}
    m = snap.manifest
    return _clean(
        {
            "available": True,
            "format": m["format"],
            "snapshot_id": snap.snapshot_id,
            "observation_hash": m["observation_hash"],
            "created_at": m["created_at"],
            "counts": m["counts"],
            "sources": [
                {
                    k: s.get(k)
                    for k in (
                        "provider",
                        "dataset",
                        "concept",
                        "publication_date",
                        "retrieved_at",
                        "n_series",
                        "n_observations",
                        "n_rejected",
                        "request",
                    )
                }
                | {"licence": (s.get("licence") or {}) | {}}
                for s in m["sources"]
            ],
            "semantics": m["semantics"],
            "reference_tables": {
                "currency_regimes": {"version": regimes()["version"], "reviewed": regimes()["last_reviewed"]},
                "benchmark_mappings": {
                    "version": benchmark_table()["version"],
                    "reviewed": benchmark_table()["last_reviewed"],
                },
            },
        }
    )


@router.get("/coverage")
def coverage(
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    usable: Annotated[
        str | None,
        Query(pattern="^(full|headline|headline_only|fx_only|none)$", description="filter by overall usability"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
) -> dict[str, Any]:
    """Which countries have headline CPI, food CPI and exchange rates, with first/last month, months present and state
    (``current``, ``stale``, ``short`` or ``none``). A summary plus one page of countries (at most 100)."""
    snap, missing = economic_context_snapshot()
    if snap is None:
        raise HTTPException(404, (missing or {}).get("reason", "no economic-context data"))
    m = _COVERAGE.get(snap.snapshot_id)
    if m is None:
        _COVERAGE.clear()
        m = _COVERAGE[snap.snapshot_id] = coverage_matrix(snap)
    sel = m
    if country:
        sel = sel[sel["country"] == country]
    if usable:
        prefix = {
            "full": "full",
            "headline": "headline CPI + FX",
            "headline_only": "headline CPI only",
            "fx_only": "FX only",
            "none": "none current",
        }[usable]
        sel = sel[sel["usable"].str.startswith(prefix)]
    names = iso3_names()
    rows = [
        {"country_name": names.get(r["country"], r["country"]), **r}
        for r in sel.iloc[offset : offset + limit].to_dict("records")
    ]
    return _clean(
        {
            "snapshot_id": snap.snapshot_id,
            "summary": coverage_summary(m),
            "total": len(sel),
            "limit": limit,
            "offset": offset,
            "items": rows,
            "note": "Counts are of countries the IMF publishes series for, not of countries with WFP prices; a country "
            "is 'current' for a concept when its series ends within 6 months of the newest data in the snapshot.",
        }
    )
