"""account creation and first payment dates, so activation can be measured

Revision ID: 0049_client_lifecycle_dates
Revises: 0048_model_price_precision
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0049_client_lifecycle_dates"
down_revision: Union[str, None] = "0048_model_price_precision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("client", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("first_paid_at", sa.DateTime(), nullable=True))
    # Backfill from the oldest operator: for a self-serve signup that row *is* created at
    # signup, and for an admin-provisioned client it is when the account was set up. Clients
    # with no operator keep NULL — an unknown cohort is reported as unknown, never invented.
    op.execute(
        """
        UPDATE client
           SET created_at = sub.first_operator
          FROM (
                SELECT client_id, MIN(created_at) AS first_operator
                  FROM operator
                 GROUP BY client_id
               ) AS sub
         WHERE client.id = sub.client_id
        """
    )
    # first_paid_at is deliberately left empty: Stripe invoices before this migration were
    # never recorded, and guessing a payment date would corrupt the very metric it feeds.


def downgrade() -> None:
    op.drop_column("client", "first_paid_at")
    op.drop_column("client", "created_at")
