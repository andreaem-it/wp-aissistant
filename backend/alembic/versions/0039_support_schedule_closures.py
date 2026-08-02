"""support schedule exceptional closures

Revision ID: 0039_schedule_closures
Revises: 0038_plugin_installations
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0039_schedule_closures"
down_revision: Union[str, None] = "0038_plugin_installations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supportschedule",
        sa.Column("closed_dates", sa.String(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("supportschedule", "closed_dates")
