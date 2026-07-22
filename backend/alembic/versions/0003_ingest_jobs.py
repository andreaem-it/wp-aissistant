"""ingest job queue

Revision ID: 0003_ingest_jobs
Revises: 0002_vector_indexes
Create Date: 2026-07-22

Adds the ingestjob table backing the background ingest worker.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ingest_jobs"
down_revision: Union[str, None] = "0002_vector_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestjob",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestjob_client_id", "ingestjob", ["client_id"])
    op.create_index("ix_ingestjob_status", "ingestjob", ["status"])


def downgrade() -> None:
    op.drop_table("ingestjob")
