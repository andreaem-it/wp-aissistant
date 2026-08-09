"""data retention after cancellation, replacing the free-plan downgrade

Revision ID: 0052_no_free_plan_retention
Revises: 0051_messaging_usage
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0052_no_free_plan_retention"
down_revision: Union[str, None] = "0051_messaging_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("client", sa.Column("data_deletion_due_at", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("deletion_reminder_sent_days", sa.Integer(), nullable=True))

    # Il piano seminato da 0005 si chiamava "Free" e costava zero: era la versione gratuita del
    # prodotto, quella a cui si finiva anche disdicendo. Non lo si cancella — dei clienti
    # potrebbero averlo assegnato, e togliere la riga li lascerebbe con un plan_id rotto — ma
    # smette di essere gratuito e di chiamarsi così. Il servizio ora dipende da billing_status,
    # quindi rinominarlo non concede né toglie accesso a nessuno.
    op.execute(
        "UPDATE plan SET name = 'Base' WHERE name = 'Free' "
        "AND NOT EXISTS (SELECT 1 FROM plan p2 WHERE p2.name = 'Base')"
    )
    op.execute("UPDATE plan SET price_cents = 100 WHERE price_cents = 0 AND yearly_price_cents = 0")

    # Chi era già stato retrocesso al piano gratuito risulta "canceled" e da oggi è sospeso.
    # Gli si dà il periodo di grazia pieno a partire da adesso invece di cancellarlo subito:
    # non ha mai ricevuto l'avviso che i suoi dati avessero una scadenza.
    op.execute(
        "UPDATE client SET data_deletion_due_at = now() + interval '90 days' "
        "WHERE billing_status = 'canceled'"
    )


def downgrade() -> None:
    op.drop_column("client", "deletion_reminder_sent_days")
    op.drop_column("client", "data_deletion_due_at")
