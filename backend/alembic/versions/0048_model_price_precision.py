"""store model prices in thousandths of a cent, so $0.152/M is not rounded to $0.15/M

Revision ID: 0048_model_price_precision
Revises: 0047_model_prices
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0048_model_price_precision"
down_revision: Union[str, None] = "0047_model_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for side in ("input", "output"):
        op.add_column(
            "modelprice",
            sa.Column(f"{side}_millicents_per_million", sa.Integer(), nullable=False, server_default="0"),
        )
        # existing rows were whole cents; the same price is 1000x in the finer unit
        op.execute(
            f"UPDATE modelprice SET {side}_millicents_per_million = {side}_cents_per_million * 1000"
        )
        op.drop_column("modelprice", f"{side}_cents_per_million")


def downgrade() -> None:
    for side in ("input", "output"):
        op.add_column(
            "modelprice",
            sa.Column(f"{side}_cents_per_million", sa.Integer(), nullable=False, server_default="0"),
        )
        # the sub-cent precision this migration existed to keep cannot survive the trip back
        op.execute(
            f"UPDATE modelprice SET {side}_cents_per_million = {side}_millicents_per_million / 1000"
        )
        op.drop_column("modelprice", f"{side}_millicents_per_million")
