"""private conversation attachments

Revision ID: 0034_attachments
Revises: 0033_push_subscriptions
"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = "0034_attachments"
down_revision: Union[str, None] = "0033_push_subscriptions"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False), sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False), sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]), sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_attachment_client_id", "attachment", ["client_id"])
    op.create_index("ix_attachment_conversation_id", "attachment", ["conversation_id"])
    op.create_index("ix_attachment_message_id", "attachment", ["message_id"])

def downgrade() -> None:
    op.drop_index("ix_attachment_message_id", table_name="attachment")
    op.drop_index("ix_attachment_conversation_id", table_name="attachment")
    op.drop_index("ix_attachment_client_id", table_name="attachment")
    op.drop_table("attachment")
