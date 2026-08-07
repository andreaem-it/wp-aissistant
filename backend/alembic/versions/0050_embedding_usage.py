"""daily rollup of embedding usage, so the margin can include it

Revision ID: 0050_embedding_usage
Revises: 0049_client_lifecycle_dates
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0050_embedding_usage"
down_revision: Union[str, None] = "0049_client_lifecycle_dates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embeddingusage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("ingest_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("query_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "model", "day", name="uq_embedding_usage_day"),
    )
    for column in ("client_id", "model", "day"):
        op.create_index(f"ix_embeddingusage_{column}", "embeddingusage", [column])
    # No backfill: embeddings made before this migration were never measured, and inventing a
    # volume would corrupt the very cost it feeds. Those days simply report nothing.


def downgrade() -> None:
    op.drop_table("embeddingusage")
