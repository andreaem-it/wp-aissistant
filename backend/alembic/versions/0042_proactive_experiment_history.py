"""immutable proactive A/B experiment history

Revision ID: 0042_proactive_history
Revises: 0041_proactive_ab_testing
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0042_proactive_history"
down_revision: Union[str, None] = "0041_proactive_ab_testing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proactiveexperiment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("rule_name", sa.String(), nullable=False, server_default=""),
        sa.Column("message_a", sa.String(), nullable=False, server_default=""),
        sa.Column("message_b", sa.String(), nullable=False, server_default=""),
        sa.Column("impressions_a", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagements_a", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions_b", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engagements_b", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("statistical_winner", sa.String(), nullable=False, server_default=""),
        sa.Column("selected_variant", sa.String(), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(), nullable=False, server_default="stopped"),
        sa.Column("operator_email", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_proactiveexperiment_client_id", "proactiveexperiment", ["client_id"])
    op.create_index("ix_proactiveexperiment_rule_id", "proactiveexperiment", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_proactiveexperiment_rule_id", table_name="proactiveexperiment")
    op.drop_index("ix_proactiveexperiment_client_id", table_name="proactiveexperiment")
    op.drop_table("proactiveexperiment")
