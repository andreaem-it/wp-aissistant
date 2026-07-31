"""proactive widget messages

Revision ID: 0026_proactive_rules
Revises: 0025_workflows
Create Date: 2026-08-01

`proactiverule` holds the contextual messages the widget can offer before the visitor writes
(by URL, time on page, exit intent or cart), with the counters used to judge whether a rule
earns its place.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_proactive_rules"
down_revision: Union[str, None] = "0025_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proactiverule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trigger_type", sa.String(), nullable=False, server_default="time_on_page"),
        sa.Column("url_pattern", sa.String(), nullable=False, server_default=""),
        sa.Column("delay_seconds", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("message", sa.String(), nullable=False, server_default=""),
        sa.Column("frequency", sa.String(), nullable=False, server_default="once_per_day"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagements", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_proactiverule_client_id", "proactiverule", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_proactiverule_client_id", table_name="proactiverule")
    op.drop_table("proactiverule")
