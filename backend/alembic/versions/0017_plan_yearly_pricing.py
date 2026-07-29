"""billing: yearly price per plan

Revision ID: 0017_plan_yearly_pricing
Revises: 0016_ingest_job_leases
Create Date: 2026-07-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_plan_yearly_pricing"
down_revision: Union[str, None] = "0016_ingest_job_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plan",
        sa.Column("yearly_price_cents", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "plan",
        sa.Column("stripe_yearly_price_id", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("plan", "stripe_yearly_price_id")
    op.drop_column("plan", "yearly_price_cents")
