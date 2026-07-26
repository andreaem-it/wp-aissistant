"""visitor contact: optional email + page url on a conversation

Revision ID: 0009_visitor_contact
Revises: 0008_message_feedback
Create Date: 2026-07-26

Adds conversation.visitor_email and conversation.visitor_url (both nullable): the visitor
can leave an email on escalation to be notified when an operator replies; visitor_url is the
page they chatted from, used as the return link in that notification.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_visitor_contact"
down_revision: Union[str, None] = "0008_message_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("visitor_email", sa.String(), nullable=True))
    op.add_column("conversation", sa.Column("visitor_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation", "visitor_url")
    op.drop_column("conversation", "visitor_email")
