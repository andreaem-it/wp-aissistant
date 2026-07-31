"""lead capture forms and captured leads

Revision ID: 0027_lead_capture
Revises: 0026_proactive_rules
Create Date: 2026-08-01

`leadform` is the tenant's qualification form (fields + per-field points + consent text) and
`lead` the captured submissions, each keeping a snapshot of the consent text the visitor
actually agreed to.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_lead_capture"
down_revision: Union[str, None] = "0026_proactive_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leadform",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False, server_default="escalation"),
        sa.Column("fields", sa.String(), nullable=False, server_default="[]"),
        sa.Column("intro", sa.String(), nullable=False, server_default=""),
        sa.Column("consent_text", sa.String(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_leadform_client_id", "leadform", ["client_id"])

    op.create_table(
        "lead",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("data", sa.String(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_text", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["form_id"], ["leadform.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_lead_client_id", "lead", ["client_id"])
    op.create_index("ix_lead_form_id", "lead", ["form_id"])
    op.create_index("ix_lead_conversation_id", "lead", ["conversation_id"])
    op.create_index("ix_lead_created_at", "lead", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_created_at", table_name="lead")
    op.drop_index("ix_lead_conversation_id", table_name="lead")
    op.drop_index("ix_lead_form_id", table_name="lead")
    op.drop_index("ix_lead_client_id", table_name="lead")
    op.drop_table("lead")

    op.drop_index("ix_leadform_client_id", table_name="leadform")
    op.drop_table("leadform")
