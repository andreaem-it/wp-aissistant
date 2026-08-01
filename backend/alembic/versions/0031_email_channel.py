"""email channel metadata and idempotent provider messages

Revision ID: 0031_email_channel
Revises: 0030_unified_channels
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0031_email_channel"
down_revision: Union[str, None] = "0030_unified_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("channel_subject", sa.String(), nullable=False, server_default=""))
    op.add_column("message", sa.Column("external_id", sa.String(), nullable=True))
    op.create_index("ix_message_external_id", "message", ["external_id"])
    op.create_unique_constraint(
        "uq_message_conversation_external_id", "message", ["conversation_id", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_message_conversation_external_id", "message", type_="unique")
    op.drop_index("ix_message_external_id", table_name="message")
    op.drop_column("message", "external_id")
    op.drop_column("conversation", "channel_subject")
