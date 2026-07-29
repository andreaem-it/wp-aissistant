"""secure visitor access to individual conversations

Revision ID: 0013_conversation_access_token
Revises: 0012_plan_monthly_quota
Create Date: 2026-07-29

Existing conversations intentionally receive an empty digest. Old widgets will get a 404,
discard their stale conversation id, and create a new token-protected conversation.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_conversation_access_token"
down_revision: Union[str, None] = "0012_plan_monthly_quota"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column("access_token_hash", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        op.f("ix_conversation_access_token_hash"),
        "conversation",
        ["access_token_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_access_token_hash"), table_name="conversation")
    op.drop_column("conversation", "access_token_hash")
