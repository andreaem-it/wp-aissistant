"""add leases and bounded retries to ingest jobs

Revision ID: 0016_ingest_job_leases
Revises: 0015_operator_session_token_hash
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_ingest_job_leases"
down_revision: Union[str, None] = "0015_operator_session_token_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingestjob", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingestjob", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("ingestjob", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.add_column("ingestjob", sa.Column("locked_at", sa.DateTime(), nullable=True))
    op.add_column("ingestjob", sa.Column("locked_by", sa.String(), nullable=False, server_default=""))
    op.execute("UPDATE ingestjob SET available_at = created_at WHERE available_at IS NULL")
    op.alter_column("ingestjob", "available_at", nullable=False)
    op.create_index(op.f("ix_ingestjob_available_at"), "ingestjob", ["available_at"])
    op.create_index(op.f("ix_ingestjob_locked_at"), "ingestjob", ["locked_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestjob_locked_at"), table_name="ingestjob")
    op.drop_index(op.f("ix_ingestjob_available_at"), table_name="ingestjob")
    op.drop_column("ingestjob", "locked_by")
    op.drop_column("ingestjob", "locked_at")
    op.drop_column("ingestjob", "available_at")
    op.drop_column("ingestjob", "max_attempts")
    op.drop_column("ingestjob", "attempts")
