"""Offline refresh of the economic-context data: retrieve, validate, snapshot.

``market-almanac context refresh`` is the only code path that talks to the IMF or the World Bank. It is meant to be
run by a maintainer (or CI), never by the API: the deployed service reads the installed artefact only.

Properties: idempotent (identical observations write nothing), resumable (completed retrievals are kept in the work
directory and reused), rate-limit aware (the shared HTTP client backs off on 429 and 5xx and honours ``Retry-After``),
and never partial (a snapshot is written only after every source has been retrieved and validated).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.context import imf_ingest as imf
from market_almanac.context import pinksheet as pink
from market_almanac.context.store import ContextStore, WriteOutcome
from market_almanac.http import HttpClient

# Licence position of each source as verified on 2026-11-20 (see docs/ECONOMIC_CONTEXT.md). ``redistribution`` is
# ``confirmed`` only when a published term permits republishing the observations unambiguously; otherwise the public
# artefact carries metadata, citations, retrieval instructions and hashes instead of the raw values.
LICENCES: dict[str, dict[str, Any]] = {
    "imf": {
        "redistribution": "confirmed",
        "authorization": "operator-attested 2026-11-20: the publisher holds the acquisition and redistribution rights",
        "terms": "https://www.imf.org/en/About/copyright-and-terms",
        "summary": (
            "IMF 'Special Terms for Statistical Data' allow downloading, copying, creating derivative works and "
            "distributing Data with attribution and a statement of material transformations. The operator attests "
            "that the necessary acquisition and redistribution permissions are held; the attribution and the "
            "transformation statement are preserved."
        ),
        "attribution": (
            "Source: International Monetary Fund, Consumer Price Index (CPI) and Exchange Rates (ER), "
            "https://data.imf.org/en/datasets/IMF.STA:CPI and https://data.imf.org/en/datasets/IMF.STA:ER. "
            "Index levels are reproduced unchanged; percentage changes shown by Market Almanac are computed from them."
        ),
    },
    "world_bank": {
        "redistribution": "confirmed",
        "authorization": "operator-attested 2026-11-20: the publisher holds the acquisition and redistribution rights",
        "terms": "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
        "summary": pink.LICENSE_NOTE,
        "attribution": (
            "The World Bank: Commodity Price Data (The Pink Sheet): data compiled by the World Bank from the "
            "third-party sources named in the workbook (e.g. Bloomberg Finance L.P., S&P Global, US Department of "
            "Agriculture). https://www.worldbank.org/en/research/commodity-markets"
        ),
    },
}


async def refresh(
    store: ContextStore,
    http: HttpClient,
    workdir: Path,
    *,
    start_period: str = imf.DEFAULT_START,
    resume: bool = True,
    pink_workbook: Path | None = None,
    pause: float = 1.0,
    now: datetime | None = None,
) -> WriteOutcome:
    """Retrieve every source and write a snapshot (or report ``unchanged``). See the module docstring."""
    now = now or datetime.now(UTC)
    retrieved = now.isoformat()
    frames: list[pd.DataFrame] = []
    series_rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    for r in await imf.retrieve_all(http, workdir, start_period=start_period, resume=resume, pause=pause):
        c = imf.CONCEPT_BY_NAME[r.concept]
        parsed = imf.parse_concept(r.path.read_text(), c, datetime.fromisoformat(r.retrieved_at), url=r.url)
        frames.append(parsed.observations)
        series_rows.extend(parsed.series)
        rejected.extend(parsed.rejected)
        sources.append(
            parsed.source
            | {
                "retrieved_at": r.retrieved_at,
                "response_sha256": r.sha256,
                "response_bytes": r.bytes,
                "start_period": start_period,
                "licence": LICENCES["imf"],
            }
        )

    if pink_workbook is None:
        url = await pink.discover_workbook_url(http)
        pink_workbook = workdir / "raw" / "pink_sheet_monthly.xlsx"
        info = await http.download(url, pink_workbook)
    else:
        url = f"file://{pink_workbook.name}"
        info = {"sha256": hashlib.sha256(pink_workbook.read_bytes()).hexdigest(), "bytes": pink_workbook.stat().st_size}
    pk = pink.parse_workbook(pink_workbook)
    frames.append(pk.observations.assign(reference_period=None, derivation=None))
    definitions: dict[str, Any] = {}
    for s in pk.series:
        sub = pk.observations[pk.observations["series_key"] == s["series_key"]]
        periods = sub["period"]
        series_rows.append(
            {
                "series_key": s["series_key"],
                "provider": "world_bank",
                "dataset": "PINK_SHEET",
                "concept": "commodity_usd",
                "benchmark_id": s["benchmark_id"],
                "label": s["label"],
                "unit": s["unit"],
                "first_period": periods.min().strftime("%Y-%m") if len(sub) else None,
                "last_period": periods.max().strftime("%Y-%m") if len(sub) else None,
                "n_obs": len(sub),
                "n_source_empty": pk.n_months
                - len(sub)
                - sum(1 for x in pk.rejected if x["series_key"] == s["series_key"]),
                "n_rejected": sum(1 for x in pk.rejected if x["series_key"] == s["series_key"]),
                "release_lag_months": 1,
                "source_ref": f"CMO-Historical-Data-Monthly.xlsx / Monthly Prices / {s['pink_name']}",
            }
        )
        if s["definition"]:
            definitions[s["benchmark_id"]] = s["definition"]
    rejected.extend(pk.rejected)
    sources.append(
        {
            "provider": "world_bank",
            "dataset": "PINK_SHEET",
            "concept": "commodity_usd",
            "request": url,
            "workbook_sha256": info["sha256"],
            "workbook_bytes": info["bytes"],
            "publication_date": pk.updated_on,
            "retrieved_at": retrieved,
            "n_series": len(pk.series),
            "n_observations": len(pk.observations),
            "n_rejected": len(pk.rejected),
            "licence": LICENCES["world_bank"],
        }
    )
    obs = pd.concat(frames, ignore_index=True)
    return store.write_snapshot(obs, series_rows, rejected, sources, definitions=definitions, now=now)
