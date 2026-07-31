"""post-conversation CSAT rating

Revision ID: 0023_conversation_rating
Revises: 0022_tags_classification
Create Date: 2026-08-01

`conversationrating` stores one 1–5 rating (plus optional comment) per conversation, left by
the visitor at the end of the chat. It is deliberately separate from `message.feedback`, which
rates a single AI answer. Who handled the conversation (AI or operator), the operator and the
department are frozen on the row so the reports stay stable if the conversation is re-assigned
later.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_conversation_rating"
down_revision: Union[str, None] = "0022_tags_classification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversationrating",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(), nullable=False, server_default=""),
        sa.Column("resolved_by", sa.String(), nullable=False, server_default="ai"),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["department.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("conversation_id", name="uq_rating_conversation"),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score"),
    )
    op.create_index("ix_conversationrating_client_id", "conversationrating", ["client_id"])
    op.create_index("ix_conversationrating_conversation_id", "conversationrating", ["conversation_id"], unique=True)
    op.create_index("ix_conversationrating_operator_id", "conversationrating", ["operator_id"])
    op.create_index("ix_conversationrating_department_id", "conversationrating", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_conversationrating_department_id", table_name="conversationrating")
    op.drop_index("ix_conversationrating_operator_id", table_name="conversationrating")
    op.drop_index("ix_conversationrating_conversation_id", table_name="conversationrating")
    op.drop_index("ix_conversationrating_client_id", table_name="conversationrating")
    op.drop_table("conversationrating")
