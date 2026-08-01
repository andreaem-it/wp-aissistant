"""visitor language on the conversation

Revision ID: 0029_conversation_language
Revises: 0028_knowledge_gap_reviews
Create Date: 2026-08-01

Existing conversations get the default language, which is what they were already answered in.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_conversation_language"
down_revision: Union[str, None] = "0028_knowledge_gap_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("language", sa.String(), nullable=False, server_default="it"))
    op.create_index("ix_conversation_language", "conversation", ["language"])


def downgrade() -> None:
    op.drop_index("ix_conversation_language", table_name="conversation")
    op.drop_column("conversation", "language")
