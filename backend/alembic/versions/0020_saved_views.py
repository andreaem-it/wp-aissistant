"""saved inbox views (personal or shared)

Revision ID: 0020_saved_views
Revises: 0019_sla_routing
Create Date: 2026-07-31

`savedview` stores a named set of inbox filters plus its ordering. It belongs to the
operator who created it; `shared` publishes it to the rest of the tenant (read-only for
everybody but the owner).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_saved_views"
down_revision: Union[str, None] = "0019_sla_routing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "savedview",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("filters", sa.String(), nullable=False, server_default="{}"),
        sa.Column("sort", sa.String(), nullable=False, server_default="recent"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_savedview_client_id", "savedview", ["client_id"])
    op.create_index("ix_savedview_operator_id", "savedview", ["operator_id"])


def downgrade() -> None:
    op.drop_index("ix_savedview_operator_id", table_name="savedview")
    op.drop_index("ix_savedview_client_id", table_name="savedview")
    op.drop_table("savedview")
