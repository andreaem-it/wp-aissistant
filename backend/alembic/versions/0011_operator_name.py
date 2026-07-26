"""operator: display name

Revision ID: 0011_operator_name
Revises: 0010_canned_and_info_fields
Create Date: 2026-07-26

Adds operator.name (display name shown to visitors, e.g. in the "… sta scrivendo"
indicator). Backfilled to '' for existing rows; falls back to email in the UI.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_operator_name"
down_revision: Union[str, None] = "0010_canned_and_info_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operator", sa.Column("name", sa.String(), nullable=True))
    op.get_bind().execute(sa.text("UPDATE operator SET name = '' WHERE name IS NULL"))
    op.alter_column("operator", "name", nullable=False, server_default="")


def downgrade() -> None:
    op.drop_column("operator", "name")
