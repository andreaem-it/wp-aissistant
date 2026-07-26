"""feedback: visitor rating on assistant messages

Revision ID: 0008_message_feedback
Revises: 0007_observability
Create Date: 2026-07-26

Adds message.feedback (nullable int: 1 = 👍, -1 = 👎, NULL = no vote), set by the chat
widget via POST /chat/feedback. Feeds the quality stats.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_message_feedback"
down_revision: Union[str, None] = "0007_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("message", sa.Column("feedback", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("message", "feedback")
