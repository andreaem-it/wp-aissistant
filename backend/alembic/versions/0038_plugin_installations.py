"""verified WordPress plugin installations

Revision ID: 0038_plugin_installations
Revises: 0037_support_schedule
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038_plugin_installations"
down_revision: Union[str, None] = "0037_support_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugininstallation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("site_origin", sa.String(), nullable=False),
        sa.Column("secret_hash", sa.String(), nullable=False),
        sa.Column("plugin_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "site_origin"),
        sa.UniqueConstraint("secret_hash"),
    )
    op.create_index("ix_plugininstallation_client_id", "plugininstallation", ["client_id"])
    op.create_index("ix_plugininstallation_site_origin", "plugininstallation", ["site_origin"])
    op.create_index("ix_plugininstallation_secret_hash", "plugininstallation", ["secret_hash"])


def downgrade() -> None:
    op.drop_index("ix_plugininstallation_secret_hash", table_name="plugininstallation")
    op.drop_index("ix_plugininstallation_site_origin", table_name="plugininstallation")
    op.drop_index("ix_plugininstallation_client_id", table_name="plugininstallation")
    op.drop_table("plugininstallation")
