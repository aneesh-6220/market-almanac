"""Engine/session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@lru_cache(maxsize=4)
def get_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):  # type: ignore[no-untyped-def]
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return eng
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@contextmanager
def session_scope(url: str) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(url), expire_on_commit=False)
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
