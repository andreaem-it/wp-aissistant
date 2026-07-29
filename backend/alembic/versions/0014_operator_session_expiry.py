"""add absolute expiry to operator sessions

Revision ID: 0014_operator_session_expiry
Revises: 0013_conversation_access_token
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_operator_session_expiry"
down_revision: Union[str, None] = "0013_conversation_access_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operatorsession", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE operatorsession SET expires_at = created_at + INTERVAL '30 days' "
        "WHERE expires_at IS NULL"
    )
    op.alter_column("operatorsession", "expires_at", nullable=False)


def downgrade() -> None:
    op.drop_column("operatorsession", "expires_at")
