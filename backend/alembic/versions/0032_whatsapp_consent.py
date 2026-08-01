"""auditable WhatsApp consent

Revision ID: 0032_whatsapp_consent
Revises: 0031_email_channel
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032_whatsapp_consent"
down_revision: Union[str, None] = "0031_email_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsappconsent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(), nullable=False, server_default=""),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "contact_id", name="uq_whatsapp_consent_tenant_contact"),
    )
    op.create_index("ix_whatsappconsent_client_id", "whatsappconsent", ["client_id"])
    op.create_index("ix_whatsappconsent_contact_id", "whatsappconsent", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_whatsappconsent_contact_id", table_name="whatsappconsent")
    op.drop_index("ix_whatsappconsent_client_id", table_name="whatsappconsent")
    op.drop_table("whatsappconsent")
