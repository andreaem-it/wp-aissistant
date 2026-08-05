"""track the billing interval and cancellation date for revenue reporting

Revision ID: 0046_subscription_revenue
Revises: 0045_subscription_period
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0046_subscription_revenue"
down_revision: Union[str, None] = "0045_subscription_period"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "client",
        sa.Column("subscription_interval", sa.String(), nullable=False, server_default=""),
    )
    op.add_column("client", sa.Column("subscription_canceled_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("client", "subscription_canceled_at")
    op.drop_column("client", "subscription_interval")
