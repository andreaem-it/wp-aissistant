"""store operator session tokens as SHA-256 digests

Revision ID: 0015_operator_session_token_hash
Revises: 0014_operator_session_expiry
Create Date: 2026-07-29

The legacy plaintext column remains nullable for a rolling deployment. Existing rows are
backfilled and new application instances write only token_hash.
"""
import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_operator_session_token_hash"
down_revision: Union[str, None] = "0014_operator_session_expiry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operatorsession", sa.Column("token_hash", sa.String(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, token FROM operatorsession")).fetchall()
    for row in rows:
        digest = hashlib.sha256(row.token.encode()).hexdigest()
        connection.execute(
            sa.text("UPDATE operatorsession SET token_hash = :digest WHERE id = :id"),
            {"digest": digest, "id": row.id},
        )
    op.alter_column("operatorsession", "token_hash", nullable=False)
    op.create_index(
        op.f("ix_operatorsession_token_hash"),
        "operatorsession",
        ["token_hash"],
        unique=True,
    )
    op.alter_column("operatorsession", "token", nullable=True)


def downgrade() -> None:
    # A digest cannot be reversed. Preserve schema reversibility by using it as an opaque token;
    # operators will need to log in again because their original plaintext was intentionally lost.
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE operatorsession SET token = token_hash WHERE token IS NULL")
    )
    op.alter_column("operatorsession", "token", nullable=False)
    op.drop_index(op.f("ix_operatorsession_token_hash"), table_name="operatorsession")
    op.drop_column("operatorsession", "token_hash")
