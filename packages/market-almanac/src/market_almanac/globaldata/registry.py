"""The global coverage registry: one honest record per country or territory.

Status ladder (each implies the ones before it, except the two failure states)::

    unsupported              no integrated price provider reports coverage
    discoverable             a provider reports coverage; nothing stored yet
    temporarily_unavailable  discoverable, but the latest ingestion attempt failed and nothing is stored
    ingested                 observations are stored as an immutable partition snapshot
    validated                the partition passed the blocking QC checks (``globaldata.qc``)
    research_eligible        validated, with at least MIN_ELIGIBLE_SERIES series meeting the eligibility rules
    forecast_evaluated       research-eligible, and at least one completed out-of-sample evaluation exists

``build_registry`` is pure: every input is passed in, which makes it testable and keeps the API
from doing anything but reading the JSON it writes.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGISTRY_VERSION = "coverage-registry-1"
STATUSES = (
    "unsupported",
    "discoverable",
    "temporarily_unavailable",
    "ingested",
    "validated",
    "research_eligible",
    "forecast_evaluated",
)
MIN_ELIGIBLE_SERIES = 10
CHIRPS_V3_LAT_LIMIT = 50.0  # CHIRPS v3 is quasi-global: 50°S to 50°N over land
WFP_LICENCE = (
    "WFP market price data via HDX HAPI: HDX HAPI Terms of Use and the licence of each underlying HDX dataset "
    "(WFP price datasets are published on HDX under CC BY-IGO); attribute WFP and HDX."
)
KNOWN_RESTRICTIONS = (
    "Prices are nominal, in the currency and unit reported by WFP; nothing is converted or deflated.",
    "HDX HAPI does not provide the original publication date of a price; as-of timing is an assumption.",
    "Market coordinates are WFP's; weather at a market is a geographic proxy, not the commodity's growing area.",
)


def classify(
    *,
    discovered: bool,
    stored: bool,
    validated: bool,
    eligible_series: int,
    evaluated: bool,
    last_attempt_failed: bool,
) -> str:
    if not stored:
        if not discovered:
            return "unsupported"
        return "temporarily_unavailable" if last_attempt_failed else "discoverable"
    if not validated:
        return "ingested"
    if eligible_series < MIN_ELIGIBLE_SERIES:
        return "validated"
    return "forecast_evaluated" if evaluated else "research_eligible"


def build_registry(
    *,
    universe: dict[str, str],
    discovery: dict[str, Any] | None,
    partitions: dict[str, dict[str, Any]],
    last_attempts: dict[str, dict[str, Any]],
    weather_countries: dict[str, int],
    macro_countries: set[str],
    agriculture_countries: set[str],
    evaluations: dict[str, list[dict[str, Any]]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Combine discovery, stored partitions, run outcomes and evaluations into the registry.

    ``partitions`` maps ISO3 to the latest partition manifest (as a dict, including ``qc``).
    ``last_attempts`` maps ISO3 to the most recent run outcome for that country.
    ``weather_countries`` maps ISO3 to the number of weather grid cells stored for it.
    ``evaluations`` maps ISO3 to a list of completed out-of-sample evaluations (id, kind, evidence class).
    """
    disc = (discovery or {}).get("countries", {})
    codes = sorted(set(universe) | set(disc) | set(partitions))
    rows = []
    for c in codes:
        d = disc.get(c)
        p = partitions.get(c)
        qc = (p or {}).get("qc", {})
        attempt = last_attempts.get(c, {})
        evals = evaluations.get(c, [])
        status = classify(
            discovered=d is not None,
            stored=p is not None,
            validated=bool(qc.get("validated")),
            eligible_series=int(qc.get("eligible_series", 0)),
            evaluated=bool(evals),
            last_attempt_failed=attempt.get("status") == "failed",
        )
        mx = qc.get("markets", 0) or 0
        in_band = qc.get("markets_within_chirps_band")
        if in_band is None and d:
            in_band = d.get("markets_within_chirps_band")
        rows.append(
            {
                "country_iso3": c,
                "name": universe.get(c) or (d or {}).get("name") or c,
                "status": status,
                "price_sources": ["hdx_hapi"] if (d or p) else [],
                "discovered": d is not None,
                "markets_listed": (d or {}).get("markets_listed"),
                "markets": qc.get("markets"),
                "commodities": qc.get("commodities"),
                "series": qc.get("series"),
                "observations": (p or {}).get("row_count"),
                "first_period": qc.get("first_period"),
                "last_period": qc.get("last_period"),
                "series_median_observations": qc.get("series_median_observations"),
                "series_with_12_obs": qc.get("series_with_12_obs"),
                "eligible_series": qc.get("eligible_series"),
                "eligible_by_commodity": qc.get("eligible_by_commodity", [])[:5],
                "market_coordinate_completeness": qc.get("market_coordinate_completeness"),
                "currencies": qc.get("currencies"),
                "price_types": qc.get("price_types"),
                "qc": {
                    "validated": qc.get("validated"),
                    "blocking": qc.get("blocking", []),
                    "invalid_prices": qc.get("invalid_prices"),
                    "conflicting_duplicates": qc.get("conflicting_duplicates"),
                    "future_dated": qc.get("future_dated"),
                    "extreme_changes": qc.get("extreme_changes"),
                    "consistency_warnings": qc.get("consistency_warnings"),
                }
                if p
                else None,
                "environment": {
                    # POWER is a global reanalysis product; availability at a point is not in question,
                    # whether it has been *extracted* for this country's markets is what we report.
                    "nasa_power_cells_stored": weather_countries.get(c, 0),
                    "chirps_v3_markets_in_band": in_band,
                    "chirps_v3_all_markets_in_band": (in_band == mx) if (p and mx) else None,
                    "chirps_v3_integrated": False,
                },
                "macro_ingested": c in macro_countries,
                "agriculture_ingested": c in agriculture_countries,
                "forecast_eligible": status in ("research_eligible", "forecast_evaluated"),
                "evaluations": evals,
                "snapshot": {
                    "snapshot_id": p.get("snapshot_id"),
                    "observation_hash": p.get("observation_hash"),
                    "file_sha256": p.get("file_sha256"),
                    "created_at": p.get("created_at"),
                    "revision": p.get("revision"),
                    "diff": p.get("diff"),
                }
                if p
                else None,
                "last_successful_refresh": (p or {}).get("created_at") if p else None,
                "last_attempt": {k: attempt.get(k) for k in ("run_id", "status", "finished_at", "error")}
                if attempt
                else None,
                "hapi_updated": (d or {}).get("hapi_updated"),
                "licence": WFP_LICENCE if (d or p) else None,
                "known_restrictions": list(KNOWN_RESTRICTIONS) if (d or p) else [],
            }
        )
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    stored = [r for r in rows if r["observations"]]
    return {
        "registry_version": REGISTRY_VERSION,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "status_definitions": {
            "unsupported": "No integrated price provider reports coverage.",
            "discoverable": "A provider reports coverage; no observations are stored yet.",
            "temporarily_unavailable": "Discoverable, but the latest ingestion attempt failed and nothing is stored.",
            "ingested": "Observations are stored as an immutable, hashed snapshot.",
            "validated": "The stored snapshot passed the blocking quality checks.",
            "research_eligible": (
                f"Validated, with at least {MIN_ELIGIBLE_SERIES} series meeting the eligibility rules "
                "(48+ monthly prices, 80% coverage, no gap over 6 months, coordinates, actual prices)."
            ),
            "forecast_evaluated": "Research-eligible and at least one completed out-of-sample evaluation exists.",
        },
        "counts": counts,
        "totals": {
            "countries_listed": len(rows),
            "countries_with_observations": len(stored),
            "observations": int(sum(r["observations"] or 0 for r in stored)),
            "series": int(sum(r["series"] or 0 for r in stored)),
            "markets": int(sum(r["markets"] or 0 for r in stored)),
            "eligible_series": int(sum(r["eligible_series"] or 0 for r in stored)),
        },
        "discovery": {
            "provider": (discovery or {}).get("provider"),
            "retrieved_at": (discovery or {}).get("retrieved_at"),
            "countries": len(disc),
        },
        "countries": rows,
    }


def write_registry(reg: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1, default=str))
    os.replace(tmp, path)
    return path


def collect_inputs(settings: Any) -> dict[str, Any]:
    """Gather the registry inputs from the lake, run logs and experiment directories (I/O)."""
    import pandas as pd

    from market_almanac.analytics.catalog import iso3_names
    from market_almanac.data.store import DatasetStore
    from market_almanac.globaldata import global_dir
    from market_almanac.globaldata.discovery import latest_discovery
    from market_almanac.globaldata.ingest import RunLog
    from market_almanac.globaldata.partitions import PartitionStore

    mode = settings.market_almanac_mode.value
    gdir = global_dir(settings)
    pstore = PartitionStore(settings.lake_dir, mode)
    partitions = {}
    for c in pstore.countries("prices"):
        m = pstore.latest("prices", c)
        if m is not None:
            partitions[c] = m.to_dict()
    last: dict[str, dict[str, Any]] = {}
    runlog = RunLog(gdir)
    for rid in runlog.list():  # oldest first, so later runs overwrite
        st = runlog.load(rid)
        for c, cs in st.countries.items():
            if cs.status != "pending":
                last[c] = {"run_id": rid, "status": cs.status, "finished_at": cs.finished_at, "error": cs.error}

    weather: dict[str, int] = {}
    for c in pstore.countries("weather_monthly"):
        m = pstore.latest("weather_monthly", c)
        if m is not None:
            locs = pd.read_parquet(pstore.path("weather_monthly", c, m.snapshot_id), columns=["location_id"])
            weather[c] = int(locs["location_id"].nunique())
    lake = DatasetStore(settings.lake_dir, mode)

    def lake_col(ds: str, cols: list[str]) -> pd.DataFrame | None:
        m = lake.latest(ds)
        return None if m is None else pd.read_parquet(lake.path(ds, m.snapshot_id), columns=cols)

    mac, agr = lake_col("macro", ["country_iso3"]), lake_col("agriculture", ["country_iso3"])
    macro: set[str] = set() if mac is None else set(mac["country_iso3"])
    agri: set[str] = set() if agr is None else set(agr["country_iso3"])
    wx, px = lake_col("weather_monthly", ["location_id"]), lake_col("prices", ["country_iso3", "lat", "lon"])
    if wx is not None and px is not None:
        # the ten-country research lake has market-local weather for its markets
        locs = set(wx["location_id"].unique())
        pr = px.dropna().drop_duplicates()
        from market_almanac.data.identity import weather_location_id

        pr["loc"] = [weather_location_id(a, b) for a, b in zip(pr["lat"], pr["lon"], strict=True)]
        for c, g in pr[pr["loc"].isin(locs)].groupby("country_iso3"):
            weather[str(c)] = max(weather.get(str(c), 0), int(g["loc"].nunique()))

    evaluations: dict[str, list[dict[str, Any]]] = {}
    exp_root = Path(settings.experiments_dir)
    superseded = _superseded_ids()
    for d in sorted(exp_root.glob("*/results.json")) if exp_root.exists() else []:
        try:
            r = json.loads(d.read_text())
        except json.JSONDecodeError:
            continue
        if r.get("status") != "completed" or r.get("experiment_id") in superseded or r.get("synthetic"):
            continue
        cfg = r.get("config", {})
        c = cfg.get("country_iso3")
        if not c:
            continue
        evaluations.setdefault(c, []).append(
            {
                "id": r.get("experiment_id"),
                "kind": "forecast_backtest",
                "study": cfg.get("study"),
                "evidence_class": cfg.get("evidence_class", "exploratory"),
                "commodities": cfg.get("commodity_codes"),
                "verdict": (r.get("conclusion") or {}).get("verdict"),
            }
        )
    for c in evaluations:
        evaluations[c] = evaluations[c][-20:]
    return {
        "universe": iso3_names(),
        "discovery": latest_discovery(gdir),
        "partitions": partitions,
        "last_attempts": last,
        "weather_countries": weather,
        "macro_countries": macro,
        "agriculture_countries": agri,
        "evaluations": evaluations,
    }


def _superseded_ids() -> set[str]:
    import yaml

    p = Path(__file__).resolve().parents[1] / "research" / "supersessions.yaml"
    if not p.exists():
        return set()
    return {str(e["old"]) for e in (yaml.safe_load(p.read_text()) or [])}


PACKAGED_REGISTRY = Path(__file__).with_name("coverage_registry.json")


def registry_path(settings: Any) -> Path:
    return Path(settings.data_dir) / "public" / settings.market_almanac_mode.value / "coverage_registry.json"


def load_registry(settings: Any) -> dict[str, Any] | None:
    """The materialized registry for this mode, else the packaged copy shipped with the code (live mode)."""
    p = registry_path(settings)
    if p.exists():
        return json.loads(p.read_text())
    if settings.market_almanac_mode.value == "live" and PACKAGED_REGISTRY.exists():
        return json.loads(PACKAGED_REGISTRY.read_text())
    return None
