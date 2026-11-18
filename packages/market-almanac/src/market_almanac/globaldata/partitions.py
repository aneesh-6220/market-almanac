"""Country-partitioned, content-addressed snapshots for global ingestion.

Layout (under the mode's lake directory)::

    partitions/<dataset>/<ISO3>/<snapshot_id>/data.parquet
    partitions/<dataset>/<ISO3>/<snapshot_id>/manifest.json

Why a second layout next to :class:`market_almanac.data.store.DatasetStore`? The original store
rewrites one merged table per dataset, which is right for the ten-country research lake but
would make every refresh of one country rewrite the whole world, and a failure half-way through
could leave the only copy in an unknown state. Here each country is its own immutable lineage:

* a snapshot is written to a hidden temporary directory and renamed into place only when the
  Parquet file and manifest are complete, so a crash never leaves a half-written snapshot that
  readers would pick up;
* revisions are detected from an *observation hash* that excludes retrieval time, so an
  unchanged re-download records ``unchanged`` instead of a new snapshot;
* a changed download writes a new snapshot whose manifest records how many observations were
  added, removed or revised against its parent. Old snapshots are never modified, so
  experiments that cite them stay reproducible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.data.schema import SCHEMA_VERSION, SCHEMAS, coerce

ISO3_RE = re.compile(r"^[A-Z]{3}$")
SNAPSHOT_RE = re.compile(r"^\d{8}T\d{6}_[0-9a-f]{6}$")
# Columns that describe *when we fetched* a record rather than *what the source says*.
VOLATILE_COLUMNS = ("retrieved_at",)


def check_iso3(code: str) -> str:
    """Validate a country code used as a path component (rejects traversal and odd input)."""
    if not isinstance(code, str) or not ISO3_RE.fullmatch(code):
        raise ValueError(f"invalid ISO3 country code: {code!r}")
    return code


def observation_hash(df: pd.DataFrame, key: tuple[str, ...]) -> str:
    """SHA-256 of the observations, independent of row order and retrieval time."""
    cols = sorted(c for c in df.columns if c not in VOLATILE_COLUMNS)
    if df.empty:
        return hashlib.sha256(b"empty|" + "|".join(cols).encode()).hexdigest()
    sort_cols = [c for c in (*key, "price") if c in df.columns]
    canon = df[cols].sort_values(sort_cols, kind="stable").reset_index(drop=True)
    h = pd.util.hash_pandas_object(canon, index=False).to_numpy()
    return hashlib.sha256("|".join(cols).encode() + h.tobytes()).hexdigest()


def revision_diff(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, int]:
    """Counts of observations added, removed and revised (same series-month, different price)."""
    if "price" not in new.columns:
        return {}
    k = ["series_id", "period"]
    o = old[[*k, "price"]].drop_duplicates()
    n = new[[*k, "price"]].drop_duplicates()
    m = o.merge(n, on=k, how="outer", suffixes=("_old", "_new"), indicator=True)
    both = m[m["_merge"] == "both"]
    return {
        "added": int((m["_merge"] == "right_only").sum()),
        "removed": int((m["_merge"] == "left_only").sum()),
        "revised": int((both["price_old"] != both["price_new"]).sum()),
    }


@dataclass
class PartitionManifest:
    snapshot_id: str
    dataset: str
    country_iso3: str
    mode: str
    created_at: str
    row_count: int
    observation_hash: str
    file_sha256: str
    schema_version: str
    provider: str
    parent_snapshot_id: str | None
    revision: str  # "initial" | "changed"
    diff: dict[str, int] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    retrieved_at_min: str | None = None
    retrieved_at_max: str | None = None
    warnings: list[str] = field(default_factory=list)
    qc: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriteOutcome:
    status: str  # "written" | "unchanged"
    manifest: PartitionManifest


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class PartitionStore:
    def __init__(self, lake_dir: Path, mode: str) -> None:
        self.root = Path(lake_dir) / "partitions"
        self.mode = mode

    def _country_dir(self, dataset: str, iso3: str) -> Path:
        if dataset not in SCHEMAS:
            raise ValueError(f"unknown dataset {dataset}")
        return self.root / dataset / check_iso3(iso3)

    def countries(self, dataset: str) -> list[str]:
        d = self.root / dataset
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir() and ISO3_RE.fullmatch(p.name))

    def list_snapshots(self, dataset: str, iso3: str) -> list[PartitionManifest]:
        d = self._country_dir(dataset, iso3)
        if not d.exists():
            return []
        out = []
        for p in d.iterdir():
            if not (p.is_dir() and SNAPSHOT_RE.fullmatch(p.name) and (p / "manifest.json").exists()):
                continue  # hidden temp dirs and anything unexpected are ignored
            try:
                out.append(PartitionManifest(**json.loads((p / "manifest.json").read_text())))
            except (TypeError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda m: (m.created_at, m.snapshot_id))

    def latest(self, dataset: str, iso3: str) -> PartitionManifest | None:
        snaps = self.list_snapshots(dataset, iso3)
        return snaps[-1] if snaps else None

    def get(self, dataset: str, iso3: str, snapshot_id: str) -> PartitionManifest:
        if not SNAPSHOT_RE.fullmatch(snapshot_id):
            raise ValueError(f"invalid snapshot id: {snapshot_id!r}")
        for m in self.list_snapshots(dataset, iso3):
            if m.snapshot_id == snapshot_id:
                return m
        raise FileNotFoundError(f"snapshot {snapshot_id} of {dataset}/{iso3} is not in this lake")

    def path(self, dataset: str, iso3: str, snapshot_id: str) -> Path:
        if not SNAPSHOT_RE.fullmatch(snapshot_id):
            raise ValueError(f"invalid snapshot id: {snapshot_id!r}")
        return self._country_dir(dataset, iso3) / snapshot_id / "data.parquet"

    def read(self, dataset: str, iso3: str, snapshot_id: str | None = None, verify: bool = False) -> pd.DataFrame:
        man = self.get(dataset, iso3, snapshot_id) if snapshot_id else self.latest(dataset, iso3)
        if man is None:
            from market_almanac.data.schema import empty_frame

            return empty_frame(SCHEMAS[dataset])
        p = self.path(dataset, iso3, man.snapshot_id)
        if verify and _sha256_file(p) != man.file_sha256:
            raise ValueError(f"integrity check failed for {dataset}/{iso3}/{man.snapshot_id}")
        return coerce(pd.read_parquet(p), SCHEMAS[dataset])

    def write(
        self,
        dataset: str,
        iso3: str,
        df: pd.DataFrame,
        *,
        provider: str,
        params: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        qc: dict[str, Any] | None = None,
    ) -> WriteOutcome:
        """Write a new snapshot for one country unless the observations are unchanged."""
        schema = SCHEMAS[dataset]
        frame = coerce(df, schema)
        frame = frame.sort_values(list(schema.key), kind="stable").reset_index(drop=True)
        ohash = observation_hash(frame, schema.key)
        parent = self.latest(dataset, iso3)
        if parent is not None and parent.observation_hash == ohash:
            return WriteOutcome("unchanged", parent)
        diff = revision_diff(self.read(dataset, iso3, parent.snapshot_id), frame) if parent else {}

        now = datetime.now(UTC)
        sid = now.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
        cdir = self._country_dir(dataset, iso3)
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = cdir / f".tmp_{sid}"
        tmp.mkdir()
        try:
            frame.to_parquet(tmp / "data.parquet", index=False)
            r = frame["retrieved_at"].dropna() if "retrieved_at" in frame.columns else pd.Series(dtype=object)
            man = PartitionManifest(
                snapshot_id=sid,
                dataset=dataset,
                country_iso3=iso3,
                mode=self.mode,
                created_at=now.isoformat(),
                row_count=len(frame),
                observation_hash=ohash,
                file_sha256=_sha256_file(tmp / "data.parquet"),
                schema_version=SCHEMA_VERSION,
                provider=provider,
                parent_snapshot_id=parent.snapshot_id if parent else None,
                revision="changed" if parent else "initial",
                diff=diff,
                params=params or {},
                retrieved_at_min=None if r.empty else pd.Timestamp(r.min()).isoformat(),
                retrieved_at_max=None if r.empty else pd.Timestamp(r.max()).isoformat(),
                warnings=list(warnings or []),
                qc=qc or {},
            )
            (tmp / "manifest.json").write_text(json.dumps(man.to_dict(), indent=2, default=str))
            os.replace(tmp, cdir / sid)  # atomic on POSIX: readers see all of it or none of it
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return WriteOutcome("written", man)

    def clean_temp(self) -> int:
        """Remove temporary directories left by an interrupted write (never touches snapshots)."""
        n = 0
        if not self.root.exists():
            return 0
        for tmp in self.root.glob("*/*/.tmp_*"):
            shutil.rmtree(tmp, ignore_errors=True)
            n += 1
        return n
