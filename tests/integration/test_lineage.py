"""Experiment lineage: migrations, supersession rules and the public default of current results."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from shocktrace.db import models as m
from shocktrace.db import repository as repo
from shocktrace.db.migrate import (
    SchemaOutOfDateError,
    current_revision,
    head_revision,
    migrate,
    require_current_schema,
)
from shocktrace.db.session import get_engine, session_scope


def test_migrations_reach_head_and_are_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    with pytest.raises(SchemaOutOfDateError, match="db-init"):
        require_current_schema(url)  # empty database: a clear instruction, not a missing-table crash
    assert migrate(url) == head_revision() == "0002"
    assert migrate(url) == "0002" and current_revision(url) == "0002"
    cols = {c["name"] for c in inspect(get_engine(url)).get_columns("experiments")}
    assert {"superseded_by", "superseded_reason", "evidence_class", "study", "variant", "method_revision"} <= cols
    require_current_schema(url)


def test_legacy_database_without_version_table_is_stamped_and_upgraded(tmp_path):
    """v0.1 SQLite databases were created with create_all and carry no alembic_version table."""
    url = f"sqlite:///{tmp_path}/legacy.db"
    eng = get_engine(url)
    m.Base.metadata.create_all(eng)
    with eng.begin() as c:  # make it look like the v0.1 schema: no lineage columns
        for col in ("superseded_by", "superseded_reason", "superseded_at", "evidence_class", "study", "variant"):
            c.exec_driver_sql(f"DROP INDEX IF EXISTS ix_experiments_{col}")
        for col in (
            "superseded_by",
            "superseded_reason",
            "superseded_at",
            "evidence_class",
            "study",
            "variant",
            "method_revision",
        ):
            c.exec_driver_sql(f"ALTER TABLE experiments DROP COLUMN {col}")
        c.exec_driver_sql(
            "INSERT INTO experiments (id, mode, name, created_at, status, synthetic, country_iso3, commodity_codes, "
            "config, config_hash, manifest, conclusion, artifact_dir, n_series, warnings) VALUES "
            "('old', 'live', 'n', '2026-11-16', 'completed', 0, 'BFA', '[]', '{}', 'h', '{}', '{}', 'x', 1, '[]')"
        )
    with pytest.raises(SchemaOutOfDateError, match="older than this version"):
        require_current_schema(url)
    assert migrate(url) == "0002"
    with session_scope(url) as s:
        row = s.get(m.Experiment, "old")
        assert row is not None and row.superseded_by is None  # history kept, defaults applied
        assert row.evidence_class == "exploratory" and row.variant == "primary"


def _exp(eid: str, mode: str = "live", **kw):  # type: ignore[no-untyped-def]
    return m.Experiment(
        id=eid,
        mode=mode,
        name=eid,
        status="completed",
        country_iso3="BFA",
        commodity_codes=["120"],
        config={},
        config_hash="h",
        manifest={},
        conclusion={},
        artifact_dir="x",
        **kw,
    )


def test_supersession_rules(tmp_path):
    url = f"sqlite:///{tmp_path}/s.db"
    migrate(url)
    with session_scope(url) as s:
        s.add_all([_exp("v1"), _exp("v2"), _exp("v3"), _exp("demo1", mode="demo")])
    with session_scope(url) as s:
        old = repo.supersede_experiment(s, "v1", "v2", "anomaly clip added")
        assert old.superseded_by == "v2" and old.superseded_reason == "anomaly clip added" and old.superseded_at
        repo.supersede_experiment(s, "v1", "v2", "same again")  # idempotent; the first reason stands
        assert s.get(m.Experiment, "v1").superseded_reason == "anomaly clip added"
        for args, msg in (
            (("v1", "v3", "r"), "already superseded"),  # never silently redirected
            (("v2", "v2", "r"), "itself"),
            (("v3", "v1", "r"), "itself superseded"),  # must point at the current run
            (("v3", "demo1", "r"), "different modes"),
            (("v3", "missing", "r"), "must exist"),
            (("v3", "v2", "  "), "reason"),
        ):
            with pytest.raises(repo.SupersessionError, match=msg):
                repo.supersede_experiment(s, *args)
        assert [e.id for e in repo.current_experiments(s, "live")] and "v1" not in [
            e.id for e in repo.current_experiments(s, "live")
        ]
        assert {e.id for e in repo.current_experiments(s, "live", include_superseded=True)} == {"v1", "v2", "v3"}
        assert s.get(m.Experiment, "v1") is not None  # nothing is deleted


@pytest.fixture(scope="module")
def client(seeded_env):  # type: ignore[no-untyped-def]
    from shocktrace_api.main import create_app

    return TestClient(create_app())


def test_api_defaults_to_current_primary_results(client, seeded_env):
    s = seeded_env["settings"]
    ids = [e["id"] for e in client.get("/api/v1/experiments").json()]
    assert len(ids) == 2
    old, new = ids[1], ids[0]
    with session_scope(s.database_url) as db:
        db.add(_exp("variant_run", mode="demo", variant="placebo_shift", study="st"))
        repo.supersede_experiment(db, old, new, "test: method revised")
    try:
        cur = client.get("/api/v1/experiments").json()
        assert [e["id"] for e in cur] == [new] and cur[0]["current"] is True
        every = {e["id"]: e for e in client.get("/api/v1/experiments?include_superseded=true").json()}
        assert set(every) == {old, new}
        assert every[old]["current"] is False and every[old]["superseded_by"] == new
        assert every[old]["superseded_reason"] == "test: method revised"
        allv = client.get("/api/v1/experiments?all_variants=true").json()
        assert {e["id"] for e in allv} == {new, "variant_run"}
        assert client.get("/api/v1/experiments?study=st&all_variants=true").json()[0]["variant"] == "placebo_shift"
        # the superseded run is still retrievable by id, and says so
        detail = client.get(f"/api/v1/experiments/{old}").json()["summary"]
        assert detail["superseded_by"] == new
        # forecasts and comparisons default to current runs; an explicit id still reaches history
        assert {f["experiment_id"] for f in client.get("/api/v1/forecasts").json()} == {new}
        assert {c["experiment_id"] for c in client.get("/api/v1/model-comparisons").json()} == {new}
        assert client.get(f"/api/v1/forecasts?experiment_id={old}").json()
        inc = client.get("/api/v1/forecasts?include_superseded=true").json()
        assert {f["experiment_id"] for f in inc} == {old, new}
    finally:
        with session_scope(s.database_url) as db:
            e = db.get(m.Experiment, old)
            e.superseded_by = e.superseded_reason = e.superseded_at = None
            db.delete(db.get(m.Experiment, "variant_run"))
