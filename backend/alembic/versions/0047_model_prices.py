"""per-model price list, to derive tenant AI cost from recorded token usage

Revision ID: 0047_model_prices
Revises: 0046_subscription_revenue
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0047_model_prices"
down_revision: Union[str, None] = "0046_subscription_revenue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "modelprice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_cents_per_million", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_cents_per_million", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(), nullable=False, server_default="eur"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_modelprice_model", "modelprice", ["model"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_modelprice_model", table_name="modelprice")
    op.drop_table("modelprice")
