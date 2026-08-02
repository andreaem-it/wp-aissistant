"""automatic Italian public holidays for support schedules

Revision ID: 0040_italian_holidays
Revises: 0039_schedule_closures
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0040_italian_holidays"
down_revision: Union[str, None] = "0039_schedule_closures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supportschedule",
        sa.Column("include_italian_holidays", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("supportschedule", "include_italian_holidays")
