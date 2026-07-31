"""conversation tags and AI classification

Revision ID: 0022_tags_classification
Revises: 0021_internal_notes
Create Date: 2026-07-31

`tag` + `conversationtag` add manual and AI labels to conversations; the `ai_*` columns on
`conversation` store the classifier's output (intent, topic, urgency). The classification is
advisory: nothing in the routing or SLA logic reads it, so a wrong or missing value can never
change how a conversation is handled.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_tags_classification"
down_revision: Union[str, None] = "0021_internal_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False, server_default=""),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.UniqueConstraint("client_id", "name", name="uq_tag_client_name"),
    )
    op.create_index("ix_tag_client_id", "tag", ["client_id"])

    op.create_table(
        "conversationtag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("conversation_id", "tag_id", name="uq_conversation_tag"),
    )
    op.create_index("ix_conversationtag_client_id", "conversationtag", ["client_id"])
    op.create_index("ix_conversationtag_conversation_id", "conversationtag", ["conversation_id"])
    op.create_index("ix_conversationtag_tag_id", "conversationtag", ["tag_id"])

    op.add_column("conversation", sa.Column("ai_intent", sa.String(), nullable=False, server_default=""))
    op.add_column("conversation", sa.Column("ai_topic", sa.String(), nullable=False, server_default=""))
    op.add_column("conversation", sa.Column("ai_urgency", sa.String(), nullable=False, server_default=""))
    op.add_column("conversation", sa.Column("ai_classified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation", "ai_classified_at")
    op.drop_column("conversation", "ai_urgency")
    op.drop_column("conversation", "ai_topic")
    op.drop_column("conversation", "ai_intent")

    op.drop_index("ix_conversationtag_tag_id", table_name="conversationtag")
    op.drop_index("ix_conversationtag_conversation_id", table_name="conversationtag")
    op.drop_index("ix_conversationtag_client_id", table_name="conversationtag")
    op.drop_table("conversationtag")

    op.drop_index("ix_tag_client_id", table_name="tag")
    op.drop_table("tag")
