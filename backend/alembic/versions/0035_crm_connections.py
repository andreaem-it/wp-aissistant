"""tenant CRM connections and lead sync state

Revision ID: 0035_crm_connections
Revises: 0034_attachments
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0035_crm_connections"
down_revision: Union[str, None] = "0034_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crmconnection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_account_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "provider"),
    )
    op.create_index("ix_crmconnection_client_id", "crmconnection", ["client_id"])
    op.create_index("ix_crmconnection_provider", "crmconnection", ["provider"])
    op.create_table(
        "crmsync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["crmconnection.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "lead_id"),
    )
    op.create_index("ix_crmsync_client_id", "crmsync", ["client_id"])
    op.create_index("ix_crmsync_connection_id", "crmsync", ["connection_id"])
    op.create_index("ix_crmsync_lead_id", "crmsync", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_crmsync_lead_id", table_name="crmsync")
    op.drop_index("ix_crmsync_connection_id", table_name="crmsync")
    op.drop_index("ix_crmsync_client_id", table_name="crmsync")
    op.drop_table("crmsync")
    op.drop_index("ix_crmconnection_provider", table_name="crmconnection")
    op.drop_index("ix_crmconnection_client_id", table_name="crmconnection")
    op.drop_table("crmconnection")
