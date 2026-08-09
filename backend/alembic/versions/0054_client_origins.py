"""i siti coperti dalla licenza diventano righe, e il piano dichiara quanti live concede

Revision ID: 0054_client_origins
Revises: 0053_internal_bootstrap_plan
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0054_client_origins"
down_revision: Union[str, None] = "0053_internal_bootstrap_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clientorigin",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="observed"),
        sa.Column("source", sa.String(), nullable=False, server_default="traffic"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "host", name="uq_client_origin_host"),
    )
    op.create_index("ix_clientorigin_client_id", "clientorigin", ["client_id"])
    op.create_index("ix_clientorigin_host", "clientorigin", ["host"])

    op.add_column("plan", sa.Column("max_live_origins", sa.Integer(), nullable=False, server_default="1"))
    # I piani interni non hanno limiti di siti, come non ne hanno di messaggi: 0 = illimitato.
    op.execute("UPDATE plan SET max_live_origins = 0 WHERE internal = true")

    # Backfill dagli origin già configurati. `Client.allowed_origins` resta al suo posto e resta
    # la sorgente che decide: finché il blocco successivo non applica il vincolo, questa tabella
    # osserva e basta. Copiare adesso ciò che è già stato configurato a mano evita di chiederlo
    # una seconda volta a chi l'aveva già dato.
    #
    # Il primo origin di ogni cliente diventa `live`, i successivi restano `observed`: quale sia
    # il dominio di produzione fra due voci scritte in una stringa non lo sa nessuno, e sceglierlo
    # a caso sarebbe peggio che lasciarlo confermare.
    op.execute(
        """
        WITH parsed AS (
            SELECT
                c.id AS client_id,
                trim(entry) AS origin,
                row_number() OVER (PARTITION BY c.id ORDER BY ordinality) AS position
            FROM client c,
                 LATERAL unnest(string_to_array(c.allowed_origins, ',')) WITH ORDINALITY AS t(entry, ordinality)
            WHERE coalesce(trim(c.allowed_origins), '') <> ''
              AND trim(entry) <> ''
        ), hosts AS (
            SELECT
                client_id,
                position,
                -- L'origin va salvato **normalizzato**: un valore con un percorso non
                -- corrisponderà mai a un header Origin del browser, che un percorso non lo
                -- porta mai. Salvare il testo grezzo qui rimetterebbe in circolo il baco che
                -- `normalize_origins` esiste per evitare, con un 403 senza spiegazione.
                CASE WHEN lower(origin) ~ '^[a-z0-9+.-]+://'
                     THEN regexp_replace(lower(origin), '^([a-z0-9+.-]+://[^/?#]+).*$', '\\1')
                     ELSE split_part(regexp_replace(lower(origin), '[?#].*$', ''), '/', 1)
                END AS origin,
                regexp_replace(
                    regexp_replace(
                        split_part(regexp_replace(lower(origin), '^[a-z0-9+.-]+://', ''), '/', 1),
                        ':[0-9]+$', ''
                    ),
                    '^www\\.', ''
                ) AS host
            FROM parsed
        ), deduped AS (
            SELECT DISTINCT ON (client_id, host) client_id, origin, host, position
            FROM hosts
            WHERE host <> ''
            ORDER BY client_id, host, position
        )
        INSERT INTO clientorigin (client_id, origin, host, kind, source, first_seen_at, last_seen_at, confirmed_at)
        SELECT
            client_id,
            origin,
            host,
            CASE WHEN position = 1 THEN 'live' ELSE 'observed' END,
            'admin',
            now(),
            now(),
            CASE WHEN position = 1 THEN now() ELSE NULL END
        FROM deduped
        """
    )

    # Le installazioni WordPress verificate per challenge sono origin di cui sappiamo già che il
    # cliente possiede il sito: sono la sorgente più affidabile che abbiamo, e vanno prese anche
    # quando `allowed_origins` era vuoto — cioè per la maggior parte dei tenant.
    op.execute(
        """
        INSERT INTO clientorigin (client_id, origin, host, kind, source, first_seen_at, last_seen_at, confirmed_at)
        SELECT DISTINCT ON (p.client_id, host.value)
            p.client_id,
            CASE WHEN lower(p.site_origin) ~ '^[a-z0-9+.-]+://'
                 THEN regexp_replace(lower(p.site_origin), '^([a-z0-9+.-]+://[^/?#]+).*$', '\\1')
                 ELSE split_part(regexp_replace(lower(p.site_origin), '[?#].*$', ''), '/', 1)
            END,
            host.value,
            'live',
            'plugin',
            now(),
            now(),
            now()
        FROM plugininstallation p,
             LATERAL (
                 SELECT regexp_replace(
                     regexp_replace(
                         split_part(regexp_replace(lower(p.site_origin), '^[a-z0-9+.-]+://', ''), '/', 1),
                         ':[0-9]+$', ''
                     ),
                     '^www\\.', ''
                 ) AS value
             ) AS host
        WHERE host.value <> ''
        ORDER BY p.client_id, host.value, p.last_sync_at DESC NULLS LAST, p.id
        ON CONFLICT (client_id, host) DO UPDATE
            SET kind = 'live', source = 'plugin', confirmed_at = now()
        """
    )


def downgrade() -> None:
    op.drop_column("plan", "max_live_origins")
    op.drop_index("ix_clientorigin_host", table_name="clientorigin")
    op.drop_index("ix_clientorigin_client_id", table_name="clientorigin")
    op.drop_table("clientorigin")
