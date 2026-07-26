"""billing: monthly chat-message quota per plan

Revision ID: 0012_plan_monthly_quota
Revises: 0011_operator_name
Create Date: 2026-07-26

Adds plan.monthly_message_limit (visitor chat messages/month that reach the AI;
0 = unlimited). Existing plans backfilled to 0 (unlimited) so nothing changes until
limits are set from the superadmin panel.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_plan_monthly_quota"
down_revision: Union[str, None] = "0011_operator_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("monthly_message_limit", sa.Integer(), nullable=True))
    op.get_bind().execute(sa.text("UPDATE plan SET monthly_message_limit = 0 WHERE monthly_message_limit IS NULL"))
    op.alter_column("plan", "monthly_message_limit", nullable=False, server_default="0")


def downgrade() -> None:
    op.drop_column("plan", "monthly_message_limit")
