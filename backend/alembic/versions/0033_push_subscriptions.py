"""operator web push subscriptions

Revision ID: 0033_push_subscriptions
Revises: 0032_whatsapp_consent
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0033_push_subscriptions"
down_revision: Union[str, None] = "0032_whatsapp_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pushsubscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("p256dh", sa.String(), nullable=False),
        sa.Column("auth", sa.String(), nullable=False),
        sa.Column("escalations", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assignments", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mentions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sla_breaches", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint"),
    )
    op.create_index("ix_pushsubscription_client_id", "pushsubscription", ["client_id"])
    op.create_index("ix_pushsubscription_operator_id", "pushsubscription", ["operator_id"])


def downgrade() -> None:
    op.drop_index("ix_pushsubscription_operator_id", table_name="pushsubscription")
    op.drop_index("ix_pushsubscription_client_id", table_name="pushsubscription")
    op.drop_table("pushsubscription")
