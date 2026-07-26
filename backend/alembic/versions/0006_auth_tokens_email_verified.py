"""auth: email verification flag on operator + auth_token table

Revision ID: 0006_auth_tokens_email_verified
Revises: 0005_billing_plans
Create Date: 2026-07-26

Adds `operator.email_verified` (self-serve signups must confirm their email before
logging in) and an `authtoken` table for single-use email tokens (password reset and
email verification). Every pre-existing operator is backfilled to email_verified=true
so upgrading never locks anyone out; the column default for new rows is false.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_auth_tokens_email_verified"
down_revision: Union[str, None] = "0005_billing_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operator", sa.Column("email_verified", sa.Boolean(), nullable=True))
    conn = op.get_bind()
    # grandfather every existing operator as verified so the new login gate doesn't lock them out
    conn.execute(sa.text("UPDATE operator SET email_verified = true WHERE email_verified IS NULL"))
    op.alter_column("operator", "email_verified", nullable=False, server_default=sa.text("false"))

    op.create_table(
        "authtoken",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"]),
    )
    op.create_index("ix_authtoken_operator_id", "authtoken", ["operator_id"])
    op.create_index("ix_authtoken_purpose", "authtoken", ["purpose"])
    op.create_index("ix_authtoken_token", "authtoken", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_authtoken_token", table_name="authtoken")
    op.drop_index("ix_authtoken_purpose", table_name="authtoken")
    op.drop_index("ix_authtoken_operator_id", table_name="authtoken")
    op.drop_table("authtoken")
    op.drop_column("operator", "email_verified")
