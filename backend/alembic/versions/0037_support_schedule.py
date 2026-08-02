"""tenant support schedule for business-hour SLA

Revision ID: 0037_support_schedule
Revises: 0036_helpdesk_connections
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037_support_schedule"
down_revision: Union[str, None] = "0036_helpdesk_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supportschedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("weekdays", sa.String(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index("ix_supportschedule_client_id", "supportschedule", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_supportschedule_client_id", table_name="supportschedule")
    op.drop_table("supportschedule")
