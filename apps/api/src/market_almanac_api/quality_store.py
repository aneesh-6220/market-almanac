"""Read the data-quality report without transferring it whole.

The live report is a single 20.9 MB JSON document (22,880 series entries, 31,504 extreme-change records). Loading
it on the API host meant moving all of it out of the database every time a fresh process first served a
quality-dependent endpoint, and on a free-tier managed PostgreSQL that transfer is metered: these reads used most of
a month's 5 GB egress allowance in three days. The endpoints only ever need a filtered, paginated slice, so the
filtering and paging happen inside the database and only that slice crosses the network.

The same queries run on SQLite (``json_each``/``json_extract``) and PostgreSQL (``json_array_elements``/``->>``), so
the offline test suite exercises the logic that production uses.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from market_almanac.db import models as m

_BIG_KEYS = ("series", "extremes", "consistency_issues")


class _Dialect:
    def __init__(self, name: str) -> None:
        self.pg = name.startswith("postgres")

    def elems(self, key: str) -> str:
        if self.pg:
            return f"json_array_elements(CAST(r.report AS json)->'{key}') WITH ORDINALITY AS e(value, ord)"
        return f"json_each(r.report, '$.{key}') AS e"

    def field(self, key: str) -> str:
        return f"(e.value->>'{key}')" if self.pg else f"json_extract(e.value, '$.{key}')"

    @property
    def value(self) -> str:
        return "CAST(e.value AS text)" if self.pg else "e.value"

    @property
    def order(self) -> str:
        return "e.ord" if self.pg else "e.key"

    @property
    def eligible(self) -> str:
        return "CAST(e.value->>'eligible' AS boolean)" if self.pg else "json_extract(e.value, '$.eligible') = 1"

    @property
    def meta(self) -> str:
        if self.pg:
            return "CAST(CAST(report AS jsonb) - 'series' - 'extremes' - 'consistency_issues' AS text)"
        return "json_remove(report, '$.series', '$.extremes', '$.consistency_issues')"

    @property
    def issues(self) -> str:
        if self.pg:
            return "CAST(CAST(report AS json)->'consistency_issues' AS text)"
        return "json_extract(report, '$.consistency_issues')"


def _loads(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str | bytes) else v


class QualityStore:
    """Bounded, per-report cache of report slices. Report ids are immutable, so entries never go stale."""

    def __init__(self, max_rows: int = 30_000, max_entries: int = 64) -> None:
        self._lock = threading.Lock()
        self._memo: OrderedDict[tuple[Any, ...], tuple[int, Any]] = OrderedDict()
        self._rows = 0
        self._max_rows, self._max_entries = max_rows, max_entries

    def clear(self) -> None:
        with self._lock:
            self._memo.clear()
            self._rows = 0

    def _cached(self, key: tuple[Any, ...], compute: Any) -> Any:
        with self._lock:
            if key in self._memo:
                self._memo.move_to_end(key)
                return self._memo[key][1]
        val, size = compute()
        with self._lock:
            if key not in self._memo and size <= self._max_rows:
                self._memo[key] = (size, val)
                self._rows += size
                while self._memo and (self._rows > self._max_rows or len(self._memo) > self._max_entries):
                    _, (n, _) = self._memo.popitem(last=False)
                    self._rows -= n
        return val

    @staticmethod
    def head(db: Session, mode: str) -> tuple[str, str] | None:
        """Id and creation time of the newest report for a mode (an index lookup; the document is not read)."""
        row = db.execute(
            select(m.DataQualityReport.id, m.DataQualityReport.created_at)
            .where(m.DataQualityReport.mode == mode)
            .order_by(desc(m.DataQualityReport.created_at))
            .limit(1)
        ).first()
        return (row[0], row[1].isoformat()) if row else None

    def meta(self, db: Session, rid: str) -> dict[str, Any]:
        """Every top-level field except the three large arrays."""
        d = _Dialect(db.get_bind().dialect.name)

        def compute() -> tuple[dict[str, Any], int]:
            v = db.execute(text(f"SELECT {d.meta} FROM data_quality_reports WHERE id = :rid"), {"rid": rid}).scalar()
            return dict(_loads(v) or {}), 1

        return dict(self._cached(("meta", rid), compute))

    def issues(self, db: Session, rid: str) -> list[str]:
        d = _Dialect(db.get_bind().dialect.name)

        def compute() -> tuple[list[str], int]:
            v = db.execute(text(f"SELECT {d.issues} FROM data_quality_reports WHERE id = :rid"), {"rid": rid}).scalar()
            out = list(_loads(v) or [])
            return out, len(out)

        return list(self._cached(("issues", rid), compute))

    @staticmethod
    def _series_where(d: _Dialect, country: str | None, series_id: str | None, eligible_only: bool) -> str:
        conds = ["r.id = :rid"]
        if country:
            conds.append(f"{d.field('country_iso3')} = :country")
        if series_id:
            conds.append(f"{d.field('series_id')} = :sid")
        if eligible_only:
            conds.append(d.eligible)
        return " AND ".join(conds)

    def series(
        self,
        db: Session,
        rid: str,
        *,
        country: str | None = None,
        series_id: str | None = None,
        eligible_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """(number of matching series, the requested page of them in report order)."""
        d = _Dialect(db.get_bind().dialect.name)
        where = self._series_where(d, country, series_id, eligible_only)
        params: dict[str, Any] = {"rid": rid, "country": country, "sid": series_id}

        def compute() -> tuple[tuple[int, list[dict[str, Any]]], int]:
            src = f"FROM data_quality_reports r, {d.elems('series')} WHERE {where}"
            total = int(db.execute(text(f"SELECT count(*) {src}"), params).scalar() or 0)
            page = f" LIMIT {int(limit)} OFFSET {int(offset)}" if limit is not None else ""
            q = f"SELECT {d.value} {src} ORDER BY {d.order}{page}"
            rows = [_loads(v) for v in db.execute(text(q), params).scalars()]
            return (total, rows), len(rows)

        total, rows = self._cached(("series", rid, country, series_id, eligible_only, limit, offset), compute)
        return total, list(rows)

    def extremes(
        self,
        db: Session,
        rid: str,
        *,
        country: str | None = None,
        series_id: str | None = None,
        eligible_only: bool = False,
        limit: int = 1000,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Extreme-change records, restricted to the matching series when any series filter is given."""
        d = _Dialect(db.get_bind().dialect.name)
        params: dict[str, Any] = {"rid": rid, "country": country, "sid": series_id}
        where = "r.id = :rid"
        if country or series_id or eligible_only:
            inner = self._series_where(d, country, series_id, eligible_only)
            where += (
                f" AND {d.field('series_id')} IN"
                f" (SELECT {d.field('series_id')} FROM data_quality_reports r, {d.elems('series')} WHERE {inner})"
            )

        def compute() -> tuple[tuple[int, list[dict[str, Any]]], int]:
            src = f"FROM data_quality_reports r, {d.elems('extremes')} WHERE {where}"
            total = int(db.execute(text(f"SELECT count(*) {src}"), params).scalar() or 0)
            q = f"SELECT {d.value} {src} ORDER BY {d.order} LIMIT {int(limit)}"
            rows = [_loads(v) for v in db.execute(text(q), params).scalars()]
            return (total, rows), len(rows)

        total, rows = self._cached(("extremes", rid, country, series_id, eligible_only, limit), compute)
        return total, list(rows)

    def eligible_ids(self, db: Session, rid: str) -> set[str]:
        """Ids of every research-eligible series (about 0.3 MB on the live report, instead of 20.9 MB)."""
        d = _Dialect(db.get_bind().dialect.name)

        def compute() -> tuple[frozenset[str], int]:
            src = f"FROM data_quality_reports r, {d.elems('series')} WHERE r.id = :rid AND {d.eligible}"
            q = f"SELECT {d.field('series_id')} {src}"
            ids = frozenset(str(v) for v in db.execute(text(q), {"rid": rid}).scalars())
            return ids, max(1, len(ids) // 20)  # ids are tiny compared with whole entries

        return set(self._cached(("eligible", rid), compute))


quality_store = QualityStore()
