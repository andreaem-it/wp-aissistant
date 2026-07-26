"""observability: AI response diagnostics, audit log, conv/ticket timestamps

Revision ID: 0007_observability
Revises: 0006_auth_tokens_email_verified
Create Date: 2026-07-26

Foundation for the admin statistics & debug surface:
- `airesponselog`: one row per /chat turn (retrieval refs + distances, model, latency,
  token usage, outcome) — the "why did it answer this way?" record.
- `auditlog`: append-only privileged-action log (who did what, when).
- `conversation.updated_at` / `conversation.closed_at` and `ticket.updated_at`, backfilled
  from created_at so response-time / duration stats have something to compute on.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_observability"
down_revision: Union[str, None] = "0006_auth_tokens_email_verified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- timestamps on existing tables (backfill from created_at) ---
    op.add_column("conversation", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("closed_at", sa.DateTime(), nullable=True))
    op.add_column("ticket", sa.Column("updated_at", sa.DateTime(), nullable=True))
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE conversation SET updated_at = created_at WHERE updated_at IS NULL"))
    conn.execute(sa.text("UPDATE ticket SET updated_at = created_at WHERE updated_at IS NULL"))
    op.alter_column("conversation", "updated_at", nullable=False)
    op.alter_column("ticket", "updated_at", nullable=False)

    # --- AI response diagnostics ---
    op.create_table(
        "airesponselog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False),
        sa.Column("tokens_completion", sa.Integer(), nullable=False),
        sa.Column("retrieved", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
    )
    op.create_index("ix_airesponselog_client_id", "airesponselog", ["client_id"])
    op.create_index("ix_airesponselog_conversation_id", "airesponselog", ["conversation_id"])

    # --- audit log ---
    op.create_table(
        "auditlog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auditlog_actor_type", "auditlog", ["actor_type"])
    op.create_index("ix_auditlog_action", "auditlog", ["action"])
    op.create_index("ix_auditlog_client_id", "auditlog", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_auditlog_client_id", table_name="auditlog")
    op.drop_index("ix_auditlog_action", table_name="auditlog")
    op.drop_index("ix_auditlog_actor_type", table_name="auditlog")
    op.drop_table("auditlog")
    op.drop_index("ix_airesponselog_conversation_id", table_name="airesponselog")
    op.drop_index("ix_airesponselog_client_id", table_name="airesponselog")
    op.drop_table("airesponselog")
    op.drop_column("ticket", "updated_at")
    op.drop_column("conversation", "closed_at")
    op.drop_column("conversation", "updated_at")
