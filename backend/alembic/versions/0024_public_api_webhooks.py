"""public API keys and signed webhooks

Revision ID: 0024_public_api_webhooks
Revises: 0023_conversation_rating
Create Date: 2026-08-01

`apikey` holds the scoped credentials of the public API (only the SHA-256 digest is stored),
`webhookendpoint` the tenant's signed destinations and `webhookdelivery` both the retry queue
and the delivery log shown in the panel.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_public_api_webhooks"
down_revision: Union[str, None] = "0023_conversation_rating"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "apikey",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("scopes", sa.String(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_apikey_client_id", "apikey", ["client_id"])
    op.create_index("ix_apikey_prefix", "apikey", ["prefix"], unique=True)
    op.create_index("ix_apikey_token_hash", "apikey", ["token_hash"], unique=True)

    op.create_table(
        "webhookendpoint",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("secret", sa.String(), nullable=False),
        sa.Column("events", sa.String(), nullable=False, server_default=""),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_webhookendpoint_client_id", "webhookendpoint", ["client_id"])

    op.create_table(
        "webhookdelivery",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("response_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(), nullable=False, server_default=""),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["endpoint_id"], ["webhookendpoint.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_webhookdelivery_client_id", "webhookdelivery", ["client_id"])
    op.create_index("ix_webhookdelivery_endpoint_id", "webhookdelivery", ["endpoint_id"])
    op.create_index("ix_webhookdelivery_event", "webhookdelivery", ["event"])
    op.create_index("ix_webhookdelivery_status", "webhookdelivery", ["status"])
    op.create_index("ix_webhookdelivery_next_attempt_at", "webhookdelivery", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_webhookdelivery_next_attempt_at", table_name="webhookdelivery")
    op.drop_index("ix_webhookdelivery_status", table_name="webhookdelivery")
    op.drop_index("ix_webhookdelivery_event", table_name="webhookdelivery")
    op.drop_index("ix_webhookdelivery_endpoint_id", table_name="webhookdelivery")
    op.drop_index("ix_webhookdelivery_client_id", table_name="webhookdelivery")
    op.drop_table("webhookdelivery")

    op.drop_index("ix_webhookendpoint_client_id", table_name="webhookendpoint")
    op.drop_table("webhookendpoint")

    op.drop_index("ix_apikey_token_hash", table_name="apikey")
    op.drop_index("ix_apikey_prefix", table_name="apikey")
    op.drop_index("ix_apikey_client_id", table_name="apikey")
    op.drop_table("apikey")
