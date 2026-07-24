"""billing: plans + client plan/billing fields

Revision ID: 0005_billing_plans
Revises: 0004_embedding_dim_1024
Create Date: 2026-07-24

Adds a `plan` table (name, price for display, per-plan rate limits, empty
stripe_price_id until Stripe is wired) and billing fields on `client`. Seeds a
"Free" plan matching today's global CHAT_RATE_LIMIT/INGEST_RATE_LIMIT defaults
and backfills every existing client onto it, so nothing changes behaviorally
until plans are actually assigned differently from the superadmin panel.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_billing_plans"
down_revision: Union[str, None] = "0004_embedding_dim_1024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("chat_rate_limit", sa.Integer(), nullable=False),
        sa.Column("ingest_rate_limit", sa.Integer(), nullable=False),
        sa.Column("stripe_price_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_name", "plan", ["name"], unique=True)

    op.add_column("client", sa.Column("plan_id", sa.Integer(), nullable=True))
    op.add_column("client", sa.Column("billing_status", sa.String(), nullable=True))
    op.add_column("client", sa.Column("stripe_customer_id", sa.String(), nullable=True))
    op.add_column("client", sa.Column("stripe_subscription_id", sa.String(), nullable=True))

    conn = op.get_bind()
    free_plan_id = conn.execute(
        sa.text(
            "INSERT INTO plan (name, price_cents, currency, chat_rate_limit, ingest_rate_limit, stripe_price_id, created_at) "
            "VALUES ('Free', 0, 'eur', 30, 60, '', now()) RETURNING id"
        )
    ).scalar_one()
    conn.execute(sa.text("UPDATE client SET plan_id = :pid, billing_status = 'active' WHERE plan_id IS NULL").bindparams(pid=free_plan_id))
    conn.execute(sa.text("UPDATE client SET stripe_customer_id = '' WHERE stripe_customer_id IS NULL"))
    conn.execute(sa.text("UPDATE client SET stripe_subscription_id = '' WHERE stripe_subscription_id IS NULL"))

    op.alter_column("client", "plan_id", nullable=False)
    op.alter_column("client", "billing_status", nullable=False)
    op.alter_column("client", "stripe_customer_id", nullable=False)
    op.alter_column("client", "stripe_subscription_id", nullable=False)
    op.create_foreign_key("client_plan_id_fkey", "client", "plan", ["plan_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("client_plan_id_fkey", "client", type_="foreignkey")
    op.drop_column("client", "stripe_subscription_id")
    op.drop_column("client", "stripe_customer_id")
    op.drop_column("client", "billing_status")
    op.drop_column("client", "plan_id")
    op.drop_index("ix_plan_name", table_name="plan")
    op.drop_table("plan")
