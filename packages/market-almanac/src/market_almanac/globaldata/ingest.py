"""Resumable, idempotent, country-partitioned ingestion of WFP prices (HDX HAPI).

A *run* is a list of target countries plus a state file that records each country's outcome
after every step (written atomically). Re-running with the same ``run_id`` resumes: countries
that already succeeded (or were unchanged) are skipped, failed and pending ones are retried.
Countries are processed with bounded concurrency; one country's failure is recorded and never
stops the others or touches an existing snapshot (see ``partitions.PartitionStore.write``).

This is batch work for a workstation or CI job. The public API never calls it.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.globaldata.partitions import PartitionStore, check_iso3
from market_almanac.globaldata.qc import summarise_partition
from market_almanac.logging import get_logger, log_event

log = get_logger("global-ingest")

TERMINAL_OK = ("succeeded", "unchanged")
MAX_COUNTRY_CONCURRENCY = 3  # HDX HAPI is a shared humanitarian service: stay polite


@dataclass
class CountryState:
    country_iso3: str
    status: str = "pending"  # pending | running | succeeded | unchanged | failed
    attempts: int = 0
    rows: int | None = None
    snapshot_id: str | None = None
    requests: int | None = None
    seconds: float | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class RunState:
    run_id: str
    dataset: str
    provider: str
    created_at: str
    params: dict[str, Any]
    countries: dict[str, CountryState]
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["summary"] = self.summary()
        return d

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.countries.values():
            out[c.status] = out.get(c.status, 0) + 1
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        d = {k: v for k, v in d.items() if k != "summary"}
        d["countries"] = {k: CountryState(**v) for k, v in d["countries"].items()}
        return cls(**d)


class RunLog:
    """Atomic JSON persistence of run states under ``<global_dir>/runs``."""

    def __init__(self, global_dir: Path) -> None:
        self.dir = Path(global_dir) / "runs"

    def path(self, run_id: str) -> Path:
        if not run_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"invalid run id: {run_id!r}")
        return self.dir / f"{run_id}.json"

    def save(self, state: RunState) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        state.updated_at = datetime.now(UTC).isoformat()
        p = self.path(state.run_id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, default=str))
        os.replace(tmp, p)

    def load(self, run_id: str) -> RunState:
        return RunState.from_dict(json.loads(self.path(run_id).read_text()))

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json")) if self.dir.exists() else []


FetchFn = Callable[[str], Awaitable[tuple[pd.DataFrame, list[str], int]]]


def new_run(countries: list[str], dataset: str = "prices", provider: str = "hdx_hapi", **params: Any) -> RunState:
    codes = sorted({check_iso3(c.upper()) for c in countries})
    rid = f"run_{datetime.now(UTC):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:4]}"
    return RunState(
        run_id=rid,
        dataset=dataset,
        provider=provider,
        created_at=datetime.now(UTC).isoformat(),
        params=params,
        countries={c: CountryState(c) for c in codes},
    )


async def execute_run(
    state: RunState,
    store: PartitionStore,
    runlog: RunLog,
    fetch: FetchFn,
    *,
    concurrency: int = 2,
    max_attempts: int = 3,
    qc: bool = True,
) -> RunState:
    """Process every country not yet in a terminal-OK state. Safe to call again to resume."""
    store.clean_temp()
    sem = asyncio.Semaphore(max(1, min(concurrency, MAX_COUNTRY_CONCURRENCY)))
    lock = asyncio.Lock()

    async def one(cs: CountryState) -> None:
        if cs.status in TERMINAL_OK or cs.attempts >= max_attempts:
            return
        async with sem:
            async with lock:
                cs.status, cs.attempts, cs.error = "running", cs.attempts + 1, None
                cs.started_at = datetime.now(UTC).isoformat()
                runlog.save(state)
            t0 = time.perf_counter()
            try:
                frame, warnings, nreq = await fetch(cs.country_iso3)
                summary = (
                    await asyncio.to_thread(summarise_partition, frame)
                    if qc and state.dataset == "prices" and len(frame)
                    else {}
                )
                out = await asyncio.to_thread(
                    store.write,
                    state.dataset,
                    cs.country_iso3,
                    frame,
                    provider=state.provider,
                    params={**state.params, "country_iso3": cs.country_iso3, "run_id": state.run_id},
                    warnings=warnings,
                    qc=summary,
                )
                cs.status = "succeeded" if out.status == "written" else "unchanged"
                cs.rows, cs.snapshot_id, cs.requests, cs.warnings = len(frame), out.manifest.snapshot_id, nreq, warnings
            except Exception as exc:  # isolate: record and continue with the other countries
                cs.status, cs.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
                log_event(log, "country ingestion failed", country=cs.country_iso3, error=cs.error)
            cs.seconds = round(time.perf_counter() - t0, 2)
            cs.finished_at = datetime.now(UTC).isoformat()
            async with lock:
                runlog.save(state)
            log_event(log, "country done", country=cs.country_iso3, status=cs.status, rows=cs.rows)

    runlog.save(state)
    await asyncio.gather(*(one(c) for c in state.countries.values()))
    runlog.save(state)
    return state


def hdx_price_fetcher(settings: Any) -> FetchFn:
    """Fetch all WFP price records for one country through the existing HDX HAPI adapter."""
    from market_almanac.providers import build_providers

    hdx = build_providers(settings)["hdx_hapi"]

    async def fetch(iso3: str) -> tuple[pd.DataFrame, list[str], int]:
        res = await hdx.fetch("food_prices", country_iso3=iso3, use_cache=False)
        return res.frame, res.warnings, res.requests_made

    return fetch
