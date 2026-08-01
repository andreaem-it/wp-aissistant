"""knowledge gap reviews

Revision ID: 0028_knowledge_gap_reviews
Revises: 0027_lead_capture
Create Date: 2026-08-01

The gaps themselves are derived from the AI response logs at query time; only the operator's
decision about each one is persisted, so a handled question stops reappearing in the list.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_knowledge_gap_reviews"
down_revision: Union[str, None] = "0027_lead_capture"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledgegapreview",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("question_hash", sa.String(), nullable=False),
        sa.Column("question", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="taught"),
        sa.Column("operator_email", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.UniqueConstraint("client_id", "question_hash", name="uq_gap_review_client_question"),
    )
    op.create_index("ix_knowledgegapreview_client_id", "knowledgegapreview", ["client_id"])
    op.create_index("ix_knowledgegapreview_question_hash", "knowledgegapreview", ["question_hash"])


def downgrade() -> None:
    op.drop_index("ix_knowledgegapreview_question_hash", table_name="knowledgegapreview")
    op.drop_index("ix_knowledgegapreview_client_id", table_name="knowledgegapreview")
    op.drop_table("knowledgegapreview")
