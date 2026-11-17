"""experiment lineage: supersession, evidence class, study and variant

Experiment rows are immutable history. When a method correction makes a result obsolete the old
row is kept and marked with ``superseded_by`` (the id of the run that replaces it) and a reason;
public listings then default to results that are not superseded. ``evidence_class`` separates
exploratory from confirmatory runs, ``study`` ties runs to a frozen protocol and ``variant``
distinguishes the primary run from sensitivity and falsification variants.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("experiments") as b:
        b.add_column(sa.Column("superseded_by", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("superseded_reason", sa.Text(), nullable=True))
        b.add_column(sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("evidence_class", sa.String(length=16), nullable=False, server_default="exploratory"))
        b.add_column(sa.Column("study", sa.String(length=80), nullable=True))
        b.add_column(sa.Column("variant", sa.String(length=32), nullable=False, server_default="primary"))
        b.add_column(sa.Column("method_revision", sa.Text(), nullable=True))
        b.create_index("ix_experiments_superseded_by", ["superseded_by"])
        b.create_index("ix_experiments_study", ["study"])


def downgrade() -> None:
    with op.batch_alter_table("experiments") as b:
        b.drop_index("ix_experiments_study")
        b.drop_index("ix_experiments_superseded_by")
        for c in (
            "method_revision",
            "variant",
            "study",
            "evidence_class",
            "superseded_at",
            "superseded_reason",
            "superseded_by",
        ):
            b.drop_column(c)
