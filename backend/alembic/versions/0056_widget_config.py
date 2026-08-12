"""la configurazione del widget esiste anche fuori da WordPress

Revision ID: 0056_widget_config
Revises: 0055_internal_unlimited_plan
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0056_widget_config"
down_revision: Union[str, None] = "0055_internal_unlimited_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "widgetconfig",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", name="uq_widget_config_client"),
    )
    op.create_index("ix_widgetconfig_client_id", "widgetconfig", ["client_id"])
    # Nessun backfill: la configurazione dei clienti WordPress vive nel loro sito e ce la
    # portiamo solo quando decidono di gestirla dal pannello. Inventare qui una riga con i
    # default farebbe apparire "configurato" ciò che non lo è, e al primo salvataggio dal
    # pannello sovrascriverebbe l'aspetto vero del loro widget con dei valori mai scelti.


def downgrade() -> None:
    op.drop_index("ix_widgetconfig_client_id", table_name="widgetconfig")
    op.drop_table("widgetconfig")
