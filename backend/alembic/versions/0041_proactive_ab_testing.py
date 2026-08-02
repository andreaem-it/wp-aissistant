"""proactive message A/B testing

Revision ID: 0041_proactive_ab_testing
Revises: 0040_italian_holidays
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0041_proactive_ab_testing"
down_revision: Union[str, None] = "0040_italian_holidays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("proactiverule", sa.Column("message_b", sa.String(), nullable=False, server_default=""))
    op.add_column("proactiverule", sa.Column("impressions_b", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("proactiverule", sa.Column("engagements_b", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("proactiverule", "engagements_b")
    op.drop_column("proactiverule", "impressions_b")
    op.drop_column("proactiverule", "message_b")
