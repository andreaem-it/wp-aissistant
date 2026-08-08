"""daily rollup of outbound messages, so the margin can include email and channels

Revision ID: 0051_messaging_usage
Revises: 0050_embedding_usage
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0051_messaging_usage"
down_revision: Union[str, None] = "0050_embedding_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messagingusage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "channel", "day", name="uq_messaging_usage_day"),
    )
    for column in ("client_id", "channel", "day"):
        op.create_index(f"ix_messagingusage_{column}", "messagingusage", [column])
    # Nessun backfill, per la stessa ragione di 0050: i messaggi usciti prima di questa
    # migrazione non sono mai stati contati, e dedurne il volume falserebbe il costo che
    # alimentano. Quei giorni semplicemente non riportano nulla.


def downgrade() -> None:
    op.drop_table("messagingusage")
