"""SLA policies, department members, routing settings and conversation SLA stamps

Revision ID: 0019_sla_routing
Revises: 0018_helpdesk_assignment
Create Date: 2026-07-31

Adds the help-desk SLA layer: `slapolicy` (per tenant, optionally narrowed to a department
and/or a priority), `departmentmember` (the round-robin pool of a queue), `routingsetting`
(per-tenant auto-assignment mode + cursor) and the SLA stamps on `conversation`.

All conversation columns are nullable / defaulted, so existing conversations keep working
with no SLA attached until one is configured and the conversation escalates.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_sla_routing"
down_revision: Union[str, None] = "0018_helpdesk_assignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slapolicy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(), nullable=False, server_default=""),
        sa.Column("first_response_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False, server_default="480"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["department_id"], ["department.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_slapolicy_client_id", "slapolicy", ["client_id"])
    op.create_index("ix_slapolicy_department_id", "slapolicy", ["department_id"])

    op.create_table(
        "departmentmember",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["department_id"], ["department.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("department_id", "operator_id", name="uq_department_member"),
    )
    op.create_index("ix_departmentmember_client_id", "departmentmember", ["client_id"])
    op.create_index("ix_departmentmember_department_id", "departmentmember", ["department_id"])
    op.create_index("ix_departmentmember_operator_id", "departmentmember", ["operator_id"])

    op.create_table(
        "routingsetting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="off"),
        sa.Column("fallback_department_id", sa.Integer(), nullable=True),
        sa.Column("last_operator_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["fallback_department_id"], ["department.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_operator_id"], ["operator.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("client_id", name="uq_routingsetting_client"),
    )
    op.create_index("ix_routingsetting_client_id", "routingsetting", ["client_id"], unique=True)

    op.add_column("conversation", sa.Column("sla_policy_id", sa.Integer(), nullable=True))
    op.add_column("conversation", sa.Column("sla_started_at", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("first_response_at", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("first_response_due_at", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("first_response_warn_at", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("resolution_due_at", sa.DateTime(), nullable=True))
    op.add_column("conversation", sa.Column("resolution_warn_at", sa.DateTime(), nullable=True))
    op.add_column(
        "conversation",
        sa.Column("first_response_breach_notified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "conversation",
        sa.Column("resolution_breach_notified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_conversation_sla_policy", "conversation", "slapolicy", ["sla_policy_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_conversation_sla_policy_id", "conversation", ["sla_policy_id"])
    op.create_index("ix_conversation_sla_started_at", "conversation", ["sla_started_at"])
    op.create_index("ix_conversation_first_response_due_at", "conversation", ["first_response_due_at"])
    op.create_index("ix_conversation_resolution_due_at", "conversation", ["resolution_due_at"])


def downgrade() -> None:
    op.drop_index("ix_conversation_resolution_due_at", table_name="conversation")
    op.drop_index("ix_conversation_first_response_due_at", table_name="conversation")
    op.drop_index("ix_conversation_sla_started_at", table_name="conversation")
    op.drop_index("ix_conversation_sla_policy_id", table_name="conversation")
    op.drop_constraint("fk_conversation_sla_policy", "conversation", type_="foreignkey")
    op.drop_column("conversation", "resolution_breach_notified")
    op.drop_column("conversation", "first_response_breach_notified")
    op.drop_column("conversation", "resolution_warn_at")
    op.drop_column("conversation", "resolution_due_at")
    op.drop_column("conversation", "first_response_warn_at")
    op.drop_column("conversation", "first_response_due_at")
    op.drop_column("conversation", "first_response_at")
    op.drop_column("conversation", "sla_started_at")
    op.drop_column("conversation", "sla_policy_id")

    op.drop_index("ix_routingsetting_client_id", table_name="routingsetting")
    op.drop_table("routingsetting")

    op.drop_index("ix_departmentmember_operator_id", table_name="departmentmember")
    op.drop_index("ix_departmentmember_department_id", table_name="departmentmember")
    op.drop_index("ix_departmentmember_client_id", table_name="departmentmember")
    op.drop_table("departmentmember")

    op.drop_index("ix_slapolicy_department_id", table_name="slapolicy")
    op.drop_index("ix_slapolicy_client_id", table_name="slapolicy")
    op.drop_table("slapolicy")
