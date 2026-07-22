"""hnsw vector indexes for chunk and product embeddings

Revision ID: 0002_vector_indexes
Revises: 0001_initial
Create Date: 2026-07-22

Adds approximate-nearest-neighbour HNSW indexes (cosine opclass, matching the
cosine_distance queries in app/rag.py) so retrieval scales as embeddings grow.

Note: these indexes are built non-concurrently inside the migration transaction,
which locks writes on the table during the build — fine for a fresh/small DB. On a
large existing table, build them out-of-band with CREATE INDEX CONCURRENTLY instead.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_vector_indexes"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_embedding_hnsw "
        "ON chunk USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_embedding_hnsw "
        "ON product USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embedding_hnsw")
