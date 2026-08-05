"""mirror the Stripe subscription period on the client

Revision ID: 0045_subscription_period
Revises: 0044_knowledge_drafts
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0045_subscription_period"
down_revision: Union[str, None] = "0044_knowledge_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("client", sa.Column("subscription_period_end", sa.DateTime(), nullable=True))
    op.add_column(
        "client",
        sa.Column(
            "subscription_cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("client", "subscription_cancel_at_period_end")
    op.drop_column("client", "subscription_period_end")
