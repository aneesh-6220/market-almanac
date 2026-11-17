"""Rehearse the production database upgrade on an isolated PostgreSQL copy.

Usage (needs the optional ``pgserver`` package, which bundles a PostgreSQL binary):

    uv run --with pgserver python scripts/ops/rehearse_db_upgrade.py --backup-dir data/backups

Steps, none of which write to the source database:

1. Read every ShockTrace table from the configured ``DATABASE_URL`` (read-only) and save a JSON
   backup of the rows.
2. Start a throw-away local PostgreSQL, create the schema at the source's current revision and
   copy the rows into it.
3. Upgrade the copy to the head revision and run ``sync_database`` (artefact registration and
   supersession lineage) against it.
4. Check that every pre-existing experiment row kept its measurements (verdict, config hash,
   conclusion) and print which experiments are current and which are superseded.

The source URL is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import MetaData, select, text

from shocktrace.config import Settings, get_settings
from shocktrace.db import models as m
from shocktrace.db.migrate import _config, current_revision, head_revision
from shocktrace.db.session import get_engine, session_scope
from shocktrace.services import sync_database

KEY_FIELDS = ("verdict", "config_hash", "conclusion", "mode", "created_at")


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        # compare instants, not the session time zone a driver attached to them
        return (v if v.tzinfo else v.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup-dir", type=Path, default=Path("data/backups"))
    args = ap.parse_args()

    import pgserver  # type: ignore[import-not-found]

    src = get_settings()
    src_url = src.database_url
    src_rev = current_revision(src_url)
    print(f"source revision: {src_rev}; head: {head_revision()}")

    # 1. read-only snapshot of the source
    src_engine = get_engine(src_url)
    meta = MetaData()
    meta.reflect(bind=src_engine)
    tables = [t for t in meta.sorted_tables if t.name != "alembic_version"]
    rows: dict[str, list[dict[str, Any]]] = {}
    with src_engine.connect() as c:
        for t in tables:
            rows[t.name] = [dict(r._mapping) for r in c.execute(select(t))]
    print("source rows:", {k: len(v) for k, v in rows.items()})
    args.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = args.backup_dir / f"db_backup_rev{src_rev}_{stamp}.json"
    backup.write_text(
        json.dumps({k: [{c: _jsonable(v) for c, v in r.items()} for r in vs] for k, vs in rows.items()}, default=str)
    )
    print(f"backup written: {backup}")

    # 2. isolated copy at the source revision
    pgdir = Path(tempfile.mkdtemp(prefix="st_pg_"))
    server = pgserver.get_server(str(pgdir), cleanup_mode="stop")
    local_url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    cfg = _config(local_url)
    command.upgrade(cfg, src_rev or "head")
    local_engine = get_engine(local_url)
    lmeta = MetaData()
    lmeta.reflect(bind=local_engine)
    with local_engine.begin() as c:
        for t in tables:
            if rows[t.name]:
                c.execute(lmeta.tables[t.name].insert(), rows[t.name])
    print("copy at revision", current_revision(local_url))

    # 3. upgrade and sync
    command.upgrade(cfg, "head")
    print("copy upgraded to", current_revision(local_url))
    local = Settings(**{**src.model_dump(), "database_url": local_url})
    res = sync_database(local)
    print(
        f"sync: snapshots {res['snapshots']}, experiments registered {len(res['experiments'])}, "
        f"superseded {len(res['superseded'])}, lineage skipped {res['lineage_skipped']}"
    )

    # 4. invariants
    before = {r["id"]: r for r in rows.get("experiments", [])}
    problems: list[str] = []
    with session_scope(local_url) as s:
        after = {e.id: e for e in s.scalars(select(m.Experiment))}
        for eid, b in before.items():
            a = after.get(eid)
            if a is None:
                problems.append(f"{eid}: row lost")
                continue
            for f in KEY_FIELDS:
                if json.dumps(_jsonable(getattr(a, f)), sort_keys=True, default=str) != json.dumps(
                    _jsonable(b[f]), sort_keys=True, default=str
                ):
                    problems.append(f"{eid}: {f} changed")
        mode = src.shocktrace_mode.value
        current = sorted(e.id for e in after.values() if e.superseded_by is None and e.mode == mode)
        superseded = sorted(f"{e.id} -> {e.superseded_by}" for e in after.values() if e.superseded_by)
        n_dup = s.execute(text("select count(*) - count(distinct id) from experiments")).scalar()
    print(f"experiments after: {len(after)} (duplicates: {n_dup}); current {src.shocktrace_mode.value}: {len(current)}")
    print("superseded:\n  " + "\n  ".join(superseded))
    stale_current = [e for e in current if e.startswith("exp_")]
    if stale_current:
        problems.append(f"pre-v1 runs still current: {stale_current}")
    print("PROBLEMS:" if problems else "OK: all prior experiment rows preserved; lineage applied")
    for p in problems:
        print("  -", p)
    server.cleanup()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
