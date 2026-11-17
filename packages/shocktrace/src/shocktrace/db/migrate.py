"""Schema migration helpers (Alembic, programmatic).

``migrate`` brings any supported database to the latest revision. Databases created by the
v0.1 ``create_all`` path have tables but no ``alembic_version``; they are stamped with the
revision their columns match and then upgraded, so no data is rewritten or lost.

``require_current_schema`` gives a clear error before a job writes to a database whose schema is
behind the code, instead of failing halfway through with a missing-column error.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from shocktrace.db.session import get_engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class SchemaOutOfDateError(RuntimeError):
    """The database schema does not match this version of ShockTrace."""


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["url"] = url
    return cfg


def head_revision() -> str:
    head = ScriptDirectory(str(MIGRATIONS)).get_current_head()
    assert head is not None
    return head


def current_revision(url: str) -> str | None:
    with get_engine(url).connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def migrate(url: str) -> str:
    """Upgrade the database to the latest schema and return the revision."""
    insp = inspect(get_engine(url))
    tables = set(insp.get_table_names())
    cfg = _config(url)
    if "experiments" in tables and "alembic_version" not in tables:
        cols = {c["name"] for c in insp.get_columns("experiments")}
        command.stamp(cfg, "0002" if "superseded_by" in cols else "0001")
    command.upgrade(cfg, "head")
    return head_revision()


def require_current_schema(url: str) -> None:
    insp = inspect(get_engine(url))
    tables = set(insp.get_table_names())
    if "experiments" not in tables:
        raise SchemaOutOfDateError(
            "the database has no ShockTrace tables: run `shocktrace db-init` (or `alembic upgrade head`) first"
        )
    cols = {c["name"] for c in insp.get_columns("experiments")}
    if "superseded_by" not in cols:
        raise SchemaOutOfDateError(
            "the database schema is older than this version of ShockTrace (experiment lineage columns are "
            "missing): run `shocktrace db-init` (or `alembic upgrade head`)"
        )
