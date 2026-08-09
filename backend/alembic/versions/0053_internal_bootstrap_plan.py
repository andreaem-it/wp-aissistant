"""the bootstrap plan is internal, not a product priced at 1 euro

Revision ID: 0053_internal_bootstrap_plan
Revises: 0052_no_free_plan_retention

La 0052 ha rinominato il vecchio piano "Free" in "Base" e gli ha messo 1 € per farlo passare
dal controllo "nessun piano gratuito", lasciandogli `monthly_message_limit = 0` (illimitato).
Il risultato era un prodotto apparente da 1 €/mese con messaggi illimitati, visibile ai clienti
in `/billing/plans`, che rendeva insensato il piano a 19 €/500 messaggi — e che non esiste su
Stripe né è pubblicizzato da nessuna parte.

Quella riga non è un piano: è il segnaposto per un account che esiste prima di aver pagato
(`Client.plan_id` non è nullable). Qui torna a essere quello, e viene marcata interna così non
compare più in nessun elenco rivolto a un cliente.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0053_internal_bootstrap_plan"
down_revision: Union[str, None] = "0052_no_free_plan_retention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("internal", sa.Boolean(), nullable=False,
                                    server_default=sa.false()))

    # Il segnaposto si riconosce da ciò che è: il piano più vecchio, senza prezzi Stripe, quindi
    # mai acquistabile da nessuno. Il nome non è un criterio affidabile — 0052 lo ha già
    # cambiato una volta, e un cliente potrebbe averne uno chiamato allo stesso modo.
    op.execute(
        """
        UPDATE plan SET
            internal = true,
            name = 'Nessun abbonamento',
            price_cents = 0,
            yearly_price_cents = 0
        WHERE id = (
            SELECT id FROM plan
            WHERE coalesce(stripe_price_id, '') = ''
              AND coalesce(stripe_yearly_price_id, '') = ''
            ORDER BY id LIMIT 1
        )
        """
    )
    # `monthly_message_limit` non si tocca: su questo modello lo zero significa *illimitato*, ma
    # non è questo piano a concedere il servizio — lo decide `billing_status`. Metterci un tetto
    # taglierebbe le gambe a un cliente creato a mano dal superadmin, che finisce su questa riga
    # ed è legittimamente attivo.


def downgrade() -> None:
    op.drop_column("plan", "internal")
