"""Immutable, content-addressed snapshots of the economic-context data, and a bounded read-side loader.

Layout (under ``<data_dir>/context/<mode>/``)::

    <snapshot_id>/observations.parquet   long table: series_key, period, value, reference_period, derivation
    <snapshot_id>/series.parquet         one row per series: coverage, base, freshness, base breaks, provenance
    <snapshot_id>/rejected.json          every observation validation refused, with its reason
    <snapshot_id>/definitions.json       the source's own definition of each benchmark (Pink Sheet Description sheet)
    <snapshot_id>/manifest.json          snapshot identity, source vintages, SHA-256 of every file, revision diff

Semantics the rest of the engine relies on:

* **Identity.** ``snapshot_id`` is a UTC timestamp plus six hex digits of the *observation hash* (retrieval time is
  excluded). Re-running a refresh that downloads identical observations writes nothing and reports ``unchanged``;
  a changed vintage writes a new snapshot whose manifest records how many observations were added, removed and
  revised against its parent. Old snapshots are never modified.
* **Three dates, never conflated.** An observation's *reference month* is ``period``. The source's *publication
  date* is the dataset-level date of the vintage retrieved (the IMF gives one for the whole dataflow; first-release
  dates of individual observations are not available and are not invented). The *retrieval date* is when this
  project downloaded it. A snapshot is a **current vintage**: revised history, read as if it were what was visible
  at the time, would be wrong, which is why the engine labels historical comparisons as exploratory.
* **Missingness is explicit.** Valid observations only are rows; empties, rejections and coverage are counted per
  series in ``series.parquet`` so "no data" can always be told apart from "not retrieved".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from market_almanac.context import ARTEFACT_FORMAT
from market_almanac.globaldata.partitions import SNAPSHOT_RE, observation_hash

OBS_FILE = "observations.parquet"
SERIES_FILE = "series.parquet"
REJECTED_FILE = "rejected.json"
DEFS_FILE = "definitions.json"
MANIFEST_FILE = "manifest.json"
SNAPSHOT_FILES = (OBS_FILE, SERIES_FILE, REJECTED_FILE, DEFS_FILE)
OBS_COLUMNS = ["series_key", "period", "value", "reference_period", "derivation"]
SERIES_COLUMNS = [
    "series_key",
    "provider",
    "dataset",
    "concept",
    "country_iso3",
    "benchmark_id",
    "label",
    "unit",
    "base_period",
    "first_period",
    "last_period",
    "n_obs",
    "n_source_empty",
    "n_rejected",
    "base_breaks",
    "release_lag_months",
    "source_ref",
]
MAX_SNAPSHOT_BYTES = 64 * 1024**2  # refuse to load more than this (a 512 MiB host must not be handed a large file)


class ContextStoreError(RuntimeError):
    """A snapshot is missing, malformed, or does not verify."""


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str | None:
    import subprocess

    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def normalise_series(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in SERIES_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["base_breaks"] = df["base_breaks"].map(lambda b: ",".join(b) if isinstance(b, list | tuple) else (b or ""))
    return df[SERIES_COLUMNS].sort_values("series_key").reset_index(drop=True)


def revision_diff(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, Any]:
    """Observations added, removed and revised (same series and month, different value) between two snapshots."""
    k = ["series_key", "period"]
    m = old[[*k, "value"]].merge(new[[*k, "value"]], on=k, how="outer", suffixes=("_old", "_new"), indicator=True)
    both = m[m["_merge"] == "both"]
    changed = ~np.isclose(both["value_old"].to_numpy(float), both["value_new"].to_numpy(float), rtol=1e-9, atol=0.0)
    rev = both[changed]
    by: dict[str, int] = {}
    for key in rev["series_key"]:
        concept = key.split(".")[1] if key.startswith("imf.") else "pink"
        by[concept] = by.get(concept, 0) + 1
    return {
        "added": int((m["_merge"] == "right_only").sum()),
        "removed": int((m["_merge"] == "left_only").sum()),
        "revised": int(changed.sum()),
        "revised_by_concept": by,
    }


@dataclass
class WriteOutcome:
    status: str  # "written" | "unchanged"
    snapshot_id: str
    manifest: dict[str, Any]


class ContextStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @classmethod
    def for_settings(cls, settings: Any) -> ContextStore:
        return cls(Path(settings.data_dir) / "context" / settings.market_almanac_mode.value)

    def snapshot_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name
            for p in self.root.iterdir()
            if p.is_dir() and SNAPSHOT_RE.fullmatch(p.name) and (p / MANIFEST_FILE).is_file()
        )

    def latest_id(self, *, with_data: bool = False) -> str | None:
        """Newest snapshot id. ``with_data`` skips metadata-only snapshots (installed from a bundle whose
        redistribution policy withheld the observations): those carry hashes and citations, not values."""
        ids = self.snapshot_ids()
        if with_data:
            ids = [i for i in ids if (self.path(i) / OBS_FILE).is_file()]
        return ids[-1] if ids else None

    def path(self, snapshot_id: str) -> Path:
        if not SNAPSHOT_RE.fullmatch(snapshot_id):
            raise ContextStoreError(f"invalid snapshot id {snapshot_id!r}")
        return self.root / snapshot_id

    def manifest(self, snapshot_id: str) -> dict[str, Any]:
        try:
            return json.loads((self.path(snapshot_id) / MANIFEST_FILE).read_text())  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextStoreError(f"snapshot {snapshot_id} has no readable manifest") from exc

    def write_snapshot(
        self,
        obs: pd.DataFrame,
        series_rows: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        *,
        definitions: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WriteOutcome:
        if obs.empty:
            raise ContextStoreError("refusing to write an empty snapshot")
        obs = obs[OBS_COLUMNS].copy()
        obs["period"] = pd.to_datetime(obs["period"])
        obs = obs.sort_values(["series_key", "period"], kind="stable").reset_index(drop=True)
        if obs.duplicated(["series_key", "period"]).any():
            raise ContextStoreError("duplicate (series, month) observations: validation must remove them first")
        series = normalise_series(series_rows)
        digest = observation_hash(obs, ("series_key", "period"))
        latest = self.latest_id(with_data=True)
        parent = self.manifest(latest) if latest else None
        if parent and parent.get("observation_hash") == digest:
            return WriteOutcome("unchanged", parent["snapshot_id"], parent)
        created = (now or datetime.now(UTC)).astimezone(UTC)
        sid = f"{created.strftime('%Y%m%dT%H%M%S')}_{digest[:6]}"
        if (self.root / sid).exists():
            raise ContextStoreError(f"snapshot {sid} already exists")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".tmp-{uuid.uuid4().hex}"
        tmp.mkdir()
        try:
            obs.to_parquet(tmp / OBS_FILE, index=False, compression="zstd")
            series.to_parquet(tmp / SERIES_FILE, index=False, compression="zstd")
            (tmp / REJECTED_FILE).write_text(json.dumps(rejected, indent=1, sort_keys=True))
            (tmp / DEFS_FILE).write_text(json.dumps(definitions or {}, indent=1, sort_keys=True))
            diff = None
            if latest:
                diff = revision_diff(ContextSnapshot(self.path(latest)).observations(), obs)
            manifest = {
                "format": ARTEFACT_FORMAT,
                "snapshot_id": sid,
                "created_at": created.isoformat(),
                "code_commit": _git_commit(),
                "observation_hash": digest,
                "parent_snapshot_id": latest,
                "data_included": "full",
                "revision": "initial" if parent is None else "changed",
                "revision_diff": diff,
                "counts": {
                    "series": len(series),
                    "series_with_observations": int((series["n_obs"].fillna(0) > 0).sum()),
                    "observations": len(obs),
                    "rejected": len(rejected),
                    "countries": int(series["country_iso3"].dropna().nunique()),
                },
                "sources": sources,
                "semantics": {
                    "vintage": "current archived vintage at retrieval; historical values may since have been revised",
                    "reference_month": "observations.period",
                    "publication_date": "dataset-level date of the retrieved vintage (per source); not per observation",
                    "retrieval_date": "sources[].retrieved_at",
                    "release_lags_are_assumptions": True,
                },
                "files": {f: _sha256(tmp / f) for f in SNAPSHOT_FILES},
                **(extra or {}),
            }
            (tmp / MANIFEST_FILE).write_text(json.dumps(manifest, indent=1, sort_keys=True))
            os.replace(tmp, self.root / sid)  # a snapshot appears whole or not at all
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return WriteOutcome("written", sid, manifest)

    def verify(self, snapshot_id: str) -> list[str]:
        """Problems found (empty when the snapshot verifies): missing files, hash mismatches, count mismatches."""
        problems: list[str] = []
        d = self.path(snapshot_id)
        try:
            m = self.manifest(snapshot_id)
        except ContextStoreError as e:
            return [str(e)]
        for f, h in m.get("files", {}).items():
            p = d / f
            if not p.is_file():
                problems.append(f"missing file {f}")
            elif _sha256(p) != h:
                problems.append(f"SHA-256 mismatch for {f}")
        if not problems and m.get("data_included", "full") == "full":
            obs = pd.read_parquet(d / OBS_FILE)
            if len(obs) != m["counts"]["observations"]:
                problems.append("observation count differs from the manifest")
            if observation_hash(obs, ("series_key", "period")) != m["observation_hash"]:
                problems.append("observation hash differs from the manifest")
        return problems


class ContextSnapshot:
    """Read-side view of one snapshot. Everything is loaded once (about 10 MB for all countries) and sliced
    in memory; no request ever reaches the network or the database."""

    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        size = sum(p.stat().st_size for p in self.dir.iterdir() if p.is_file()) if self.dir.is_dir() else 0
        if size > MAX_SNAPSHOT_BYTES:
            raise ContextStoreError(f"snapshot is {size} bytes, above the {MAX_SNAPSHOT_BYTES} byte load limit")
        try:
            self.manifest: dict[str, Any] = json.loads((self.dir / MANIFEST_FILE).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextStoreError(f"{self.dir.name}: no readable manifest") from exc
        self.snapshot_id: str = self.manifest["snapshot_id"]
        self._obs: pd.DataFrame | None = None
        self._series: pd.DataFrame | None = None
        self._idx: dict[str, np.ndarray] | None = None
        self._defs: dict[str, Any] | None = None

    @property
    def has_data(self) -> bool:
        """False for a metadata-only snapshot (observations withheld by the redistribution policy)."""
        return (self.dir / OBS_FILE).is_file()

    def observations(self) -> pd.DataFrame:
        if not self.has_data:
            raise ContextStoreError(f"{self.snapshot_id}: metadata-only snapshot (observations were not redistributed)")
        if self._obs is None:
            self._obs = pd.read_parquet(self.dir / OBS_FILE)
        return self._obs

    def series_table(self) -> pd.DataFrame:
        if self._series is None:
            self._series = pd.read_parquet(self.dir / SERIES_FILE).set_index("series_key", drop=False)
        return self._series

    def definitions(self) -> dict[str, Any]:
        if self._defs is None:
            self._defs = json.loads((self.dir / DEFS_FILE).read_text())
        return self._defs

    def _index(self) -> dict[str, np.ndarray]:
        if self._idx is None:
            obs = self.observations()
            self._idx = {str(k): v for k, v in obs.groupby("series_key", sort=False).indices.items()}
        return self._idx

    def has(self, key: str) -> bool:
        return key in self._index()

    def series(self, key: str) -> pd.Series:
        """Valid observations of one series, indexed by month (empty if it has none)."""
        pos = self._index().get(key)
        if pos is None:
            return pd.Series(dtype=float, name=key)
        o = self.observations().iloc[pos]
        return pd.Series(o["value"].to_numpy(float), index=pd.DatetimeIndex(o["period"]), name=key).sort_index()

    def reference_periods(self, key: str) -> pd.Series:
        pos = self._index().get(key)
        if pos is None:
            return pd.Series(dtype=object, name=key)
        o = self.observations().iloc[pos]
        return pd.Series(o["reference_period"].to_numpy(object), index=pd.DatetimeIndex(o["period"])).sort_index()

    def row(self, key: str) -> dict[str, Any] | None:
        t = self.series_table()
        if key not in t.index:
            return None
        r = t.loc[key]
        return {k: (None if pd.isna(v) else v) for k, v in r.to_dict().items()}

    def countries(self) -> list[str]:
        return sorted(self.series_table()["country_iso3"].dropna().unique())

    def source(self, provider: str, dataset: str | None = None) -> dict[str, Any] | None:
        for s in self.manifest.get("sources", []):
            if s.get("provider") == provider and (dataset is None or s.get("dataset") == dataset):
                return s  # type: ignore[no-any-return]
        return None


def snapshot_id_ok(s: str | None) -> bool:
    return bool(s and re.fullmatch(SNAPSHOT_RE.pattern, s))
