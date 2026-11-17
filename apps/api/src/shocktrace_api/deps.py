"""Dependencies: settings, DB sessions and a snapshot-keyed dataset cache."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from shocktrace.config import Settings, get_settings
from shocktrace.data.store import DatasetStore
from shocktrace.db.session import get_engine


def settings_dep() -> Settings:
    return get_settings()


def db_dep() -> Iterator[Session]:
    s = sessionmaker(bind=get_engine(get_settings().database_url), expire_on_commit=False)()
    try:
        yield s
    finally:
        s.close()


class DataCache:
    """Caches whole (small) snapshot frames in memory keyed by snapshot id.

    Snapshots are immutable, so cache entries never go stale; a new snapshot simply has a
    new key. The latest-snapshot lookup is re-checked on every call (cheap directory scan).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._results: dict[str, tuple[float, dict[str, Any]]] = {}
        self._quality: dict[str, tuple[str, dict[str, Any]]] = {}

    def store(self) -> DatasetStore:
        s = get_settings()
        return DatasetStore(s.lake_dir, s.shocktrace_mode.value)

    def frame(self, dataset: str) -> tuple[pd.DataFrame, str | None]:
        st = self.store()
        latest = st.latest(dataset)
        if latest is None:
            return st.read(dataset), None
        key = (st.mode, dataset, latest.snapshot_id)
        with self._lock:
            if key not in self._frames:
                self._frames = {k: v for k, v in self._frames.items() if k[:2] != key[:2]}
                self._frames[key] = st.read(dataset, latest.snapshot_id)
            return self._frames[key], latest.snapshot_id

    def quality(self, db: Any, mode: str) -> tuple[dict[str, Any], str, str] | None:
        """Latest data-quality report for a mode, cached by report id.

        Live reports can be tens of MB (one entry per series), so only the id is queried on each
        request and the body is fetched once per new report.
        """
        from sqlalchemy import desc, select

        from shocktrace.db import models as m

        head = db.execute(
            select(m.DataQualityReport.id, m.DataQualityReport.created_at)
            .where(m.DataQualityReport.mode == mode)
            .order_by(desc(m.DataQualityReport.created_at))
            .limit(1)
        ).first()
        if head is None:
            return None
        rid, created = head
        with self._lock:
            hit = self._quality.get(mode)
            if hit and hit[0] == rid:
                return hit[1], rid, created.isoformat()
        body = db.get(m.DataQualityReport, rid).report
        with self._lock:
            self._quality[mode] = (rid, body)
        return body, rid, created.isoformat()

    def results(self, artifact_dir: str) -> dict[str, Any]:
        p = Path(artifact_dir) / "results.json"
        if not p.exists():
            raise HTTPException(404, "experiment artifacts not found on this server")
        mtime = p.stat().st_mtime
        with self._lock:
            hit = self._results.get(artifact_dir)
            if hit and hit[0] == mtime:
                return hit[1]
        data = json.loads(p.read_text())
        with self._lock:
            self._results[artifact_dir] = (mtime, data)
        return data


cache = DataCache()
