---
block: embedding-storage-costs
owner: claude
started_at: 2026-08-07T22:00:00+02:00
expires_at: 2026-08-08T22:00:00+02:00
branch: main
---

Obiettivo: chiudere il debito «il margine copre solo l'inferenza» aggiungendo il costo degli
**embedding** (ingest e domande in chat) e dello **storage** degli allegati al calcolo per tenant.

Perimetro previsto:
- `backend/app/db.py` e migrazione `0050` (rollup giornaliero dell'uso embedding)
- `backend/app/costs.py`, `backend/app/rag.py`
- `backend/app/main.py`/`routers/admin.py` solo se serve esporre nuovi campi
- `backend/tests/test_costs.py`
- `panel/src/Admin.jsx`, `README.md`, `docs/handoff.md`

Fuori perimetro:
- costi di email e canali: restano dichiarati come non contati
- ricavi, azioni commerciali, funnel
