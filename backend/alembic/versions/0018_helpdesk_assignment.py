"""helpdesk assignment, priorities and departments

Revision ID: 0018_helpdesk_assignment
Revises: 0017_plan_yearly_pricing
Create Date: 2026-07-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_helpdesk_assignment"
down_revision: Union[str, None] = "0017_plan_yearly_pricing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "department",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "name", name="uq_department_client_name"),
    )
    op.create_index("ix_department_client_id", "department", ["client_id"])
    op.add_column("conversation", sa.Column("priority", sa.String(), nullable=False, server_default="normal"))
    op.add_column("conversation", sa.Column("assigned_operator_id", sa.Integer(), nullable=True))
    op.add_column("conversation", sa.Column("department_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_conversation_assigned_operator", "conversation", "operator", ["assigned_operator_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_conversation_department", "conversation", "department", ["department_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_conversation_priority", "conversation", ["priority"])
    op.create_index("ix_conversation_assigned_operator_id", "conversation", ["assigned_operator_id"])
    op.create_index("ix_conversation_department_id", "conversation", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_department_id", table_name="conversation")
    op.drop_index("ix_conversation_assigned_operator_id", table_name="conversation")
    op.drop_index("ix_conversation_priority", table_name="conversation")
    op.drop_constraint("fk_conversation_department", "conversation", type_="foreignkey")
    op.drop_constraint("fk_conversation_assigned_operator", "conversation", type_="foreignkey")
    op.drop_column("conversation", "department_id")
    op.drop_column("conversation", "assigned_operator_id")
    op.drop_column("conversation", "priority")
    op.drop_index("ix_department_client_id", table_name="department")
    op.drop_table("department")
