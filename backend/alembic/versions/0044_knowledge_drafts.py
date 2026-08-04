"""knowledge article drafts from gap clusters

Revision ID: 0044_knowledge_drafts
Revises: 0043_workflow_scheduled_actions
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0044_knowledge_drafts"
down_revision: Union[str, None] = "0043_workflow_scheduled_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledgedraft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("question_hash", sa.String(), nullable=False),
        sa.Column("questions", sa.String(), nullable=False, server_default="[]"),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("baseline_occurrences", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column("ingest_job_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["ingest_job_id"], ["ingestjob.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "question_hash"),
    )
    for column in ("client_id", "question_hash", "status"):
        op.create_index(f"ix_knowledgedraft_{column}", "knowledgedraft", [column])


def downgrade() -> None:
    op.drop_table("knowledgedraft")
