"""il piano interno illimitato: quello con cui serviamo il nostro sito e il pannello

Revision ID: 0055_internal_unlimited_plan
Revises: 0054_client_origins
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0055_internal_unlimited_plan"
down_revision: Union[str, None] = "0054_client_origins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLAN_NAME = "Interno — Illimitato"


def upgrade() -> None:
    # `code` dà un'identità stabile ai piani che il codice deve saper trovare. Prima
    # `default_plan_id()` sceglieva "il piano con l'id più basso": una regola che ha funzionato
    # finché il segnaposto era l'unico piano interno, e che con un secondo piano interno — che
    # concede tutto — assegnerebbe accesso illimitato a ogni nuovo iscritto su un database in
    # cui quello nasce per primo. Il nome non può fare da chiave: è modificabile dal pannello.
    op.add_column("plan", sa.Column("code", sa.String(), nullable=False, server_default=""))
    op.create_index("ix_plan_code", "plan", ["code"])

    # Il segnaposto esistente: la riga interna più vecchia, che è quella creata da
    # `default_plan_id()` prima di questa migrazione.
    op.execute(
        """
        UPDATE plan SET code = 'bootstrap'
        WHERE id = (SELECT id FROM plan WHERE internal = true ORDER BY id LIMIT 1)
        """
    )

    # La 0054 aveva dato domini illimitati a **tutti** i piani interni. Sul segnaposto è
    # incoerente: è la riga che non concede nulla — a decidere l'erogazione è `billing_status` —
    # e non c'è ragione perché conceda il solo privilegio dei siti illimitati. Conta per i tenant
    # creati a mano dal superadmin, che nascono `active` proprio su questa riga.
    op.execute("UPDATE plan SET max_live_origins = 1 WHERE code = 'bootstrap'")

    # Il secondo piano interno, e di natura diversa dal primo: «Nessun abbonamento» è il
    # segnaposto per un account che esiste prima di aver pagato, questo è il piano con cui
    # serviamo noi stessi. Entrambi sono `internal` — non vendibili, fuori da ogni elenco
    # rivolto a un cliente — ma questo concede tutto invece di niente.
    #
    # `monthly_message_limit = 0` è già la semantica di illimitato, e `max_live_origins = 0`
    # quella di "quanti domini vuoi": serviremo il sito marketing e il pannello dallo stesso
    # tenant, che sono due origin diversi.
    #
    # I limiti di frequenza sono alti perché dietro questo unico `client_id` c'è il traffico di
    # tutti i pannelli dei clienti insieme: il limitatore resta per IP (`chat:{client}:{ip}`),
    # quindi gli utenti restano separati, ma il tetto per-piano non deve essere il collo.
    op.execute(
        sa.text(
            """
            INSERT INTO plan (
                name, code, price_cents, currency, chat_rate_limit, ingest_rate_limit,
                monthly_message_limit, max_live_origins, yearly_price_cents,
                stripe_price_id, stripe_yearly_price_id, internal, created_at
            )
            SELECT :name, 'internal_unlimited', 0, 'eur', 600, 600, 0, 0, 0, '', '', true, now()
            WHERE NOT EXISTS (SELECT 1 FROM plan WHERE code = 'internal_unlimited')
            """
        ).bindparams(name=PLAN_NAME)
    )


def downgrade() -> None:
    # Solo se non lo sta usando nessuno: cancellare un piano a cui un client punta lascerebbe una
    # riga orfana su una foreign key non nullable, cioè un tenant che non si può più caricare.
    op.execute("UPDATE plan SET max_live_origins = 0 WHERE code = 'bootstrap'")
    op.execute(
        "DELETE FROM plan WHERE code = 'internal_unlimited' "
        "AND NOT EXISTS (SELECT 1 FROM client WHERE client.plan_id = plan.id)"
    )
    op.drop_index("ix_plan_code", table_name="plan")
    op.drop_column("plan", "code")
