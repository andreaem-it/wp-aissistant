"""durable delayed workflow actions

Revision ID: 0043_workflow_scheduled_actions
Revises: 0042_proactive_history
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0043_workflow_scheduled_actions"
down_revision: Union[str, None] = "0042_proactive_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflowscheduledaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("actions", sa.String(), nullable=False),
        sa.Column("data", sa.String(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("cancel_on_reply", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("baseline_message_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("client_id", "workflow_id", "conversation_id", "status", "run_at"):
        op.create_index(f"ix_workflowscheduledaction_{column}", "workflowscheduledaction", [column])


def downgrade() -> None:
    op.drop_table("workflowscheduledaction")
