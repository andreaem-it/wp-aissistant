---
block: activation-and-risk
owner: claude
started_at: 2026-08-06T15:40:00+02:00
expires_at: 2026-08-07T15:40:00+02:00
branch: main
---

Obiettivo: misurare l'**attivazione** (account creato → plugin collegato → prima chat → prima
risposta utile → primo pagamento) e segnalare i **clienti a rischio** con motivi espliciti, non
con un punteggio opaco. Serve la data di creazione del cliente, che oggi non esiste.

Perimetro previsto:
- `backend/app/growth.py` (nuovo)
- `backend/app/billing.py` — sola registrazione del primo pagamento riuscito
- `backend/app/db.py` e migrazione `0049` (`Client.created_at`, `Client.first_paid_at`)
- `backend/app/main.py` — **solo** i nuovi `/admin/activation` e `/admin/at-risk`
- `backend/tests/test_growth.py` (nuovo)
- `panel/src/Admin.jsx`, `panel/src/adminApi.js`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/handoff.md`

Fuori perimetro:
- `/admin/revenue`, `/admin/costs`, azioni commerciali (già rilasciati)
- divisione di `main.py` in router: è un blocco a sé
- helpdesk, inbox, analytics, canali, plugin, API pubblica
