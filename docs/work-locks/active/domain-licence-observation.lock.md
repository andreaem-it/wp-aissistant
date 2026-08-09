---
block: domain-licence-observation
owner: claude
started_at: 2026-08-10T00:40:00+02:00
expires_at: 2026-08-13T00:40:00+02:00
branch: main
---

Obiettivo: fondamenta della licenza legata al dominio, **in sola osservazione**. Al termine il
backend sa classificare e registrare i domini da cui arriva il traffico widget (live, staging,
locale), conosce gli slot concessi dal piano e ha il backfill dagli origin già verificati — ma
**non rifiuta ancora nulla**. L'applicazione (fail closed) è un blocco successivo, dopo che
l'osservazione ha raccolto dati e i clienti hanno confermato i propri domini.

Motivo della divisione: oggi la maggioranza dei tenant ha `allowed_origins` vuoto e il binding
fallisce aperto. Applicare subito spegnerebbe il widget a tutto il parco clienti insieme. Vedi
`docs/embedded-assistant-roadmap.md` §5.

Perimetro previsto:
- `backend/app/origins.py` (nuovo: vocabolario chiuso delle etichette di staging, classificazione
  live/staging/locale, regole di equivalenza, validazione)
- `backend/app/db.py` (`ClientOrigin`, `Plan.max_live_origins`)
- `backend/alembic/versions/0054_client_origins.py`
- `backend/app/deps.py` (registrazione dell'origin osservato in `rate_limit_chat`; nessun rifiuto
  nuovo)
- `backend/app/cors.py` (allowlist letta dalla tabella invece che dalla colonna di testo)
- `backend/tests/test_origins.py` (nuovo), `backend/tests/test_routes.py` se cambiano i path
- `docs/embedded-assistant-roadmap.md`, `README.md`, `docs/competitor-feature-backlog.md`

Fuori perimetro (liberi per un altro agente):
- `panel/`, `wp-plugin/`, `website/`, `sdk/`
- L'applicazione fail closed e il rifiuto delle richieste senza header `Origin`
- Gli endpoint tenant-scoped di gestione domini e il configuratore (fase 3 della roadmap)
- Il piano interno Illimitato e il nostro tenant (fase 0 della roadmap)
