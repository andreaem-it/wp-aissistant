"""unified channel contacts and conversation threading

Revision ID: 0030_unified_channels
Revises: 0029_conversation_language
Create Date: 2026-08-01

Existing web conversations are backfilled to one Contact per tenant/browser visitor id.
Legacy visitor fields remain untouched so deployed widgets keep working unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_unified_channels"
down_revision: Union[str, None] = "0029_conversation_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False, server_default="web"),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "channel", "external_id", name="uq_contact_tenant_channel_external"),
    )
    op.create_index("ix_contact_client_id", "contact", ["client_id"])
    op.create_index("ix_contact_channel", "contact", ["channel"])
    op.create_index("ix_contact_external_id", "contact", ["external_id"])
    op.create_index("ix_contact_email", "contact", ["email"])

    op.add_column("conversation", sa.Column("channel", sa.String(), nullable=False, server_default="web"))
    op.add_column("conversation", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.add_column("conversation", sa.Column("external_thread_id", sa.String(), nullable=False, server_default=""))
    op.create_foreign_key("fk_conversation_contact", "conversation", "contact", ["contact_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_conversation_channel", "conversation", ["channel"])
    op.create_index("ix_conversation_contact_id", "conversation", ["contact_id"])
    op.create_index("ix_conversation_external_thread_id", "conversation", ["external_thread_id"])

    op.execute(sa.text("""
        INSERT INTO contact (client_id, channel, external_id, email, name, created_at, updated_at)
        SELECT client_id, 'web', visitor_id, max(visitor_email), '', min(created_at), max(updated_at)
        FROM conversation
        GROUP BY client_id, visitor_id
    """))
    op.execute(sa.text("""
        UPDATE conversation AS c
        SET contact_id = ct.id
        FROM contact AS ct
        WHERE ct.client_id = c.client_id
          AND ct.channel = 'web'
          AND ct.external_id = c.visitor_id
    """))


def downgrade() -> None:
    op.drop_index("ix_conversation_external_thread_id", table_name="conversation")
    op.drop_index("ix_conversation_contact_id", table_name="conversation")
    op.drop_index("ix_conversation_channel", table_name="conversation")
    op.drop_constraint("fk_conversation_contact", "conversation", type_="foreignkey")
    op.drop_column("conversation", "external_thread_id")
    op.drop_column("conversation", "contact_id")
    op.drop_column("conversation", "channel")
    op.drop_index("ix_contact_email", table_name="contact")
    op.drop_index("ix_contact_external_id", table_name="contact")
    op.drop_index("ix_contact_channel", table_name="contact")
    op.drop_index("ix_contact_client_id", table_name="contact")
    op.drop_table("contact")
