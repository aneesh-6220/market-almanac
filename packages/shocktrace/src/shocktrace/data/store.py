"""Versioned Parquet dataset store with DuckDB queries.

Layout::

    <lake_dir>/<dataset>/<snapshot_id>/data.parquet
    <lake_dir>/<dataset>/<snapshot_id>/manifest.json

A snapshot is immutable. Ingestion merges new records into the previous snapshot
(idempotent upsert on the schema key) and writes a *new* snapshot, so every experiment can
cite exact snapshot IDs. Large observation tables live only here (not duplicated in SQL);
PostgreSQL stores the snapshot registry and analysis metadata.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from shocktrace.data.schema import SCHEMA_VERSION, SCHEMAS, coerce, validate


@dataclass
class SnapshotManifest:
    snapshot_id: str
    dataset: str
    mode: str
    created_at: str
    row_count: int
    content_hash: str
    schema_version: str
    providers: list[str]
    parent_snapshot_id: str | None
    params: dict[str, Any] = field(default_factory=dict)
    retrieved_at_min: str | None = None
    retrieved_at_max: str | None = None
    warnings: list[str] = field(default_factory=list)
    synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def frame_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return hashlib.sha256(b"empty").hexdigest()[:16]
    h = pd.util.hash_pandas_object(df.reset_index(drop=True), index=False).values
    return hashlib.sha256(h.tobytes()).hexdigest()[:16]


class DatasetStore:
    def __init__(self, lake_dir: Path, mode: str) -> None:
        self.root = Path(lake_dir)
        self.mode = mode

    def _dir(self, dataset: str) -> Path:
        if dataset not in SCHEMAS:
            raise ValueError(f"unknown dataset {dataset}")
        return self.root / dataset

    def list_snapshots(self, dataset: str) -> list[SnapshotManifest]:
        d = self._dir(dataset)
        if not d.exists():
            return []
        out = []
        for m in d.glob("*/manifest.json"):
            try:
                out.append(SnapshotManifest(**json.loads(m.read_text())))
            except (TypeError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda s: s.created_at)

    def latest(self, dataset: str) -> SnapshotManifest | None:
        snaps = self.list_snapshots(dataset)
        return snaps[-1] if snaps else None

    def path(self, dataset: str, snapshot_id: str) -> Path:
        return self._dir(dataset) / snapshot_id / "data.parquet"

    def read(self, dataset: str, snapshot_id: str | None = None) -> pd.DataFrame:
        schema = SCHEMAS[dataset]
        if snapshot_id is None:
            latest = self.latest(dataset)
            if latest is None:
                from shocktrace.data.schema import empty_frame

                return empty_frame(schema)
            snapshot_id = latest.snapshot_id
        return coerce(pd.read_parquet(self.path(dataset, snapshot_id)), schema)

    def write(
        self,
        dataset: str,
        df: pd.DataFrame,
        *,
        providers: list[str],
        params: dict[str, Any] | None = None,
        merge_with_latest: bool = True,
        warnings: list[str] | None = None,
        synthetic: bool = False,
        replace_keys_for: dict[str, list[Any]] | None = None,
    ) -> SnapshotManifest:
        """Write a new immutable snapshot.

        With ``merge_with_latest`` the new rows upsert into the previous snapshot on the
        schema key (newer retrievals win), which makes refreshes idempotent and incremental.
        """
        schema = SCHEMAS[dataset]
        new = coerce(df, schema)
        parent = self.latest(dataset) if merge_with_latest else None
        if parent is not None:
            old = self.read(dataset, parent.snapshot_id)
            if replace_keys_for:
                mask = pd.Series(True, index=old.index)
                for col, vals in replace_keys_for.items():
                    mask &= old[col].isin(vals)
                old = old[~mask]
            combined = pd.concat([old, new], ignore_index=True)
        else:
            combined = new
        sort_cols = [c for c in ("retrieved_at",) if c in combined.columns]
        if sort_cols:
            combined = combined.sort_values(sort_cols, kind="stable")
        # Conflicting duplicate price records are legitimately preserved (flagged) by providers.
        allow_dups = dataset == "prices"
        if allow_dups:
            combined = combined.drop_duplicates(
                subset=[*schema.key, "price"] if "price" in combined.columns else list(schema.key), keep="last"
            )
        else:
            combined = combined.drop_duplicates(subset=list(schema.key), keep="last")
        combined = combined.sort_values(list(schema.key), kind="stable").reset_index(drop=True)
        warn = list(warnings or []) + validate(combined, schema, allow_duplicate_keys=allow_dups)

        sid = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
        target = self._dir(dataset) / sid
        target.mkdir(parents=True, exist_ok=False)
        combined.to_parquet(target / "data.parquet", index=False)
        r = combined["retrieved_at"] if "retrieved_at" in combined.columns else pd.Series(dtype="datetime64[ns, UTC]")
        manifest = SnapshotManifest(
            snapshot_id=sid,
            dataset=dataset,
            mode=self.mode,
            created_at=datetime.now(UTC).isoformat(),
            row_count=len(combined),
            content_hash=frame_hash(combined),
            schema_version=SCHEMA_VERSION,
            providers=sorted(set(providers) | set(parent.providers if parent else [])),
            parent_snapshot_id=parent.snapshot_id if parent else None,
            params=params or {},
            retrieved_at_min=None if r.dropna().empty else r.min().isoformat(),
            retrieved_at_max=None if r.dropna().empty else r.max().isoformat(),
            warnings=warn,
            synthetic=synthetic,
        )
        (target / "manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2, default=str))
        return manifest

    def prune(self, dataset: str, keep: int = 5) -> int:
        snaps = self.list_snapshots(dataset)
        removed = 0
        for s in snaps[:-keep]:
            shutil.rmtree(self._dir(dataset) / s.snapshot_id, ignore_errors=True)
            removed += 1
        return removed

    def query(self, sql: str, params: list[Any] | None = None, datasets: tuple[str, ...] = ()) -> pd.DataFrame:
        """Run a parameterised DuckDB query; datasets are exposed as views of the latest snapshot."""
        con = duckdb.connect(database=":memory:")
        try:
            for ds in datasets:
                latest = self.latest(ds)
                if latest is None:
                    cols = ", ".join(f"NULL AS {c}" for c in SCHEMAS[ds].columns)
                    con.execute(f"CREATE VIEW {ds} AS SELECT {cols} WHERE FALSE")
                else:
                    p = str(self.path(ds, latest.snapshot_id)).replace("'", "''")
                    con.execute(f"CREATE VIEW {ds} AS SELECT * FROM read_parquet('{p}')")
            return con.execute(sql, params or []).df()
        finally:
            con.close()
