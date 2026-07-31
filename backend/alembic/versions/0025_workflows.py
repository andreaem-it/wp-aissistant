"""no-code workflows (trigger, conditions, actions) and their run log

Revision ID: 0025_workflows
Revises: 0024_public_api_webhooks
Create Date: 2026-08-01

`workflow` stores the tenant rules (conditions/actions as validated JSON) and `workflowrun`
every evaluation, matching or not, so an operator can see why an automation did or didn't fire.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_workflows"
down_revision: Union[str, None] = "0024_public_api_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("conditions", sa.String(), nullable=False, server_default="[]"),
        sa.Column("actions", sa.String(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
    )
    op.create_index("ix_workflow_client_id", "workflow", ["client_id"])
    op.create_index("ix_workflow_trigger", "workflow", ["trigger"])

    op.create_table(
        "workflowrun",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied", sa.String(), nullable=False, server_default="[]"),
        sa.Column("error", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workflowrun_client_id", "workflowrun", ["client_id"])
    op.create_index("ix_workflowrun_workflow_id", "workflowrun", ["workflow_id"])
    op.create_index("ix_workflowrun_conversation_id", "workflowrun", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_workflowrun_conversation_id", table_name="workflowrun")
    op.drop_index("ix_workflowrun_workflow_id", table_name="workflowrun")
    op.drop_index("ix_workflowrun_client_id", table_name="workflowrun")
    op.drop_table("workflowrun")

    op.drop_index("ix_workflow_trigger", table_name="workflow")
    op.drop_index("ix_workflow_client_id", table_name="workflow")
    op.drop_table("workflow")
