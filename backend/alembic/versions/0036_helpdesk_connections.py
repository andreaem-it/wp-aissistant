"""tenant helpdesk connections and ticket export state

Revision ID: 0036_helpdesk_connections
Revises: 0035_crm_connections
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0036_helpdesk_connections"
down_revision: Union[str, None] = "0035_crm_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "helpdeskconnection",
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
    op.create_index("ix_helpdeskconnection_client_id", "helpdeskconnection", ["client_id"])
    op.create_index("ix_helpdeskconnection_provider", "helpdeskconnection", ["provider"])
    op.create_table(
        "helpdeskexport",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("external_url", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["helpdeskconnection.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "ticket_id"),
    )
    op.create_index("ix_helpdeskexport_client_id", "helpdeskexport", ["client_id"])
    op.create_index("ix_helpdeskexport_connection_id", "helpdeskexport", ["connection_id"])
    op.create_index("ix_helpdeskexport_ticket_id", "helpdeskexport", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_helpdeskexport_ticket_id", table_name="helpdeskexport")
    op.drop_index("ix_helpdeskexport_connection_id", table_name="helpdeskexport")
    op.drop_index("ix_helpdeskexport_client_id", table_name="helpdeskexport")
    op.drop_table("helpdeskexport")
    op.drop_index("ix_helpdeskconnection_provider", table_name="helpdeskconnection")
    op.drop_index("ix_helpdeskconnection_client_id", table_name="helpdeskconnection")
    op.drop_table("helpdeskconnection")
