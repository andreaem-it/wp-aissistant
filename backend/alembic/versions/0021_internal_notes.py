"""internal notes and operator mentions

Revision ID: 0021_internal_notes
Revises: 0020_saved_views
Create Date: 2026-07-31

`internalnote` holds operator-only notes on a conversation (never returned by the visitor
endpoints) and `notemention` the operators tagged in them, with the read stamp used by the
panel to show unread mentions.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_internal_notes"
down_revision: Union[str, None] = "0020_saved_views"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "internalnote",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_internalnote_client_id", "internalnote", ["client_id"])
    op.create_index("ix_internalnote_conversation_id", "internalnote", ["conversation_id"])
    op.create_index("ix_internalnote_operator_id", "internalnote", ["operator_id"])

    op.create_table(
        "notemention",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["note_id"], ["internalnote.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notemention_client_id", "notemention", ["client_id"])
    op.create_index("ix_notemention_note_id", "notemention", ["note_id"])
    op.create_index("ix_notemention_conversation_id", "notemention", ["conversation_id"])
    op.create_index("ix_notemention_operator_id", "notemention", ["operator_id"])


def downgrade() -> None:
    op.drop_index("ix_notemention_operator_id", table_name="notemention")
    op.drop_index("ix_notemention_conversation_id", table_name="notemention")
    op.drop_index("ix_notemention_note_id", table_name="notemention")
    op.drop_index("ix_notemention_client_id", table_name="notemention")
    op.drop_table("notemention")

    op.drop_index("ix_internalnote_operator_id", table_name="internalnote")
    op.drop_index("ix_internalnote_conversation_id", table_name="internalnote")
    op.drop_index("ix_internalnote_client_id", table_name="internalnote")
    op.drop_table("internalnote")
