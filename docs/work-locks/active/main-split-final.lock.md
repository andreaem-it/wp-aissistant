---
block: main-split-final
owner: claude
started_at: 2026-08-07T18:00:00+02:00
expires_at: 2026-08-08T18:00:00+02:00
branch: main
---

Obiettivo: **fase finale** della divisione di `main.py`. Estrarre le tre aree rimaste — `/admin`,
account e autenticazione, ingest e knowledge base — lasciando in `main.py` solo creazione
dell'app, middleware, lifespan, `/health`, `/metrics` e la registrazione dei router.

Perimetro previsto:
- `backend/app/routers/admin.py`, `accounts.py`, `knowledge.py` (nuovi)
- `backend/app/main.py`, `backend/conftest.py`, `backend/tests/`, `docs/handoff.md`

Fuori perimetro:
- panel, plugin, worker Cloudflare
