"""embedding dimension 768 -> 1024 (bge-m3)

Revision ID: 0004_embedding_dim_1024
Revises: 0003_ingest_jobs
Create Date: 2026-07-23

Switch the embedding columns to 1024 dims for Cloudflare Workers AI's bge-m3
(multilingual). A dimension change is NOT a value-preserving cast, so the existing
768-dim vectors are blanked to NULL — re-embed afterwards via POST /admin/reembed
(retrieval skips rows with a NULL embedding in the meantime). Pair with EMBED_DIM=1024.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_embedding_dim_1024"
down_revision: Union[str, None] = "0003_ingest_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _resize(dim: int) -> None:
    # HNSW indexes are tied to the column dimension, so drop them, resize (clearing values),
    # then rebuild.
    op.execute("DROP INDEX IF EXISTS ix_chunk_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_product_embedding_hnsw")
    op.execute(f"ALTER TABLE chunk ALTER COLUMN embedding TYPE vector({dim}) USING NULL::vector({dim})")
    op.execute(f"ALTER TABLE product ALTER COLUMN embedding TYPE vector({dim}) USING NULL::vector({dim})")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunk_embedding_hnsw ON chunk USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_embedding_hnsw ON product USING hnsw (embedding vector_cosine_ops)")


def upgrade() -> None:
    _resize(1024)


def downgrade() -> None:
    _resize(768)
