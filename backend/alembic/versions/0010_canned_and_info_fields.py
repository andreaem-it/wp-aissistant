"""operator tools: canned responses, info field definitions, conversation.info

Revision ID: 0010_canned_and_info_fields
Revises: 0009_visitor_contact
Create Date: 2026-07-26

Per-client `cannedresponse` (saved replies) and `infofield` (definitions of structured
info fields shown on a conversation), plus `conversation.info` (JSON dict of the values
the operator fills in, keyed by InfoField.key).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_canned_and_info_fields"
down_revision: Union[str, None] = "0009_visitor_contact"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("info", sa.String(), nullable=True))

    op.create_table(
        "cannedresponse",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_cannedresponse_client_id", "cannedresponse", ["client_id"])

    op.create_table(
        "infofield",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_infofield_client_id", "infofield", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_infofield_client_id", table_name="infofield")
    op.drop_table("infofield")
    op.drop_index("ix_cannedresponse_client_id", table_name="cannedresponse")
    op.drop_table("cannedresponse")
    op.drop_column("conversation", "info")
