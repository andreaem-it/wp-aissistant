---
block: domain-licence-enforcement
owner: claude
started_at: 2026-08-12T00:15:00+02:00
expires_at: 2026-08-15T00:15:00+02:00
branch: main
---

Obiettivo: applicare la licenza legata al dominio. Un widget su un dominio non registrato smette
di funzionare, `ClientOrigin` diventa la sorgente di verità delle decisioni, e il tenant può
registrare da sé il proprio dominio live e quello di staging entro gli slot del piano.

Perché adesso e non a scaglioni: la fase di osservazione (blocco `domain-licence-observation`)
ha girato tre giorni in produzione e ha raccolto **zero** righe nuove — non per un difetto, ma
perché non è passato traffico chat dopo il rilascio. Il parco è di 4 tenant, tutti di prova, e
l'unico con traffico storico ha già il dominio registrato dall'installazione WordPress
verificata. Non c'è nessuno da rompere: la finestra per applicare senza gradualità è ora, prima
dei clienti veri. Dati e ragionamento in `docs/embedded-assistant-roadmap.md` §5.

Perimetro previsto:
- `backend/app/origins.py` (slot, registrazione, motivi di rifiuto, sorgente per le decisioni)
- `backend/app/deps.py` (`rate_limit_chat`: fail closed; rifiuto delle chiamate senza `Origin`
  sui percorsi widget)
- `backend/app/cors.py` (allowlist dalla tabella)
- `backend/app/routers/accounts.py` (endpoint tenant-scoped sui propri domini; checklist)
- `backend/app/routers/admin.py` (`/admin/clients/*/origins` scrive la tabella)
- `backend/app/routers/widget.py` (callback order lookup e prova installazione dalla tabella)
- `backend/alembic/versions/0055_*.py`
- `backend/tests/test_origins.py`, `backend/tests/test_routes.py`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro (liberi per un altro agente):
- **`panel/`** — Codex ci sta lavorando. `Client.allowed_origins` resta quindi in vita come
  **specchio derivato**, scritto dallo stesso punto che scrive la tabella e mai letto per
  decidere: si toglie quando il pannello sarà passato ai nuovi endpoint.
- `wp-plugin/`, `website/`, `sdk/`
- Il configuratore e la UI di installazione (fase 3 della roadmap)
- Il tenant interno e il piano Illimitato (fase 0 della roadmap)
