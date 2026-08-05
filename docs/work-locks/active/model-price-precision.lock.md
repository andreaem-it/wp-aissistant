---
block: model-price-precision
owner: claude
started_at: 2026-08-05T22:00:00+02:00
expires_at: 2026-08-06T22:00:00+02:00
branch: main
---

Obiettivo: il listino modelli accetta il prezzo per milione di token **come lo pubblica il
provider** (es. `0.152`), senza perdita di precisione, e i costi non mescolano valute diverse
spacciandole per euro.

Perimetro previsto:
- `backend/app/costs.py`
- `backend/app/db.py` e migrazione `0048` (prezzi in millesimi di centesimo)
- `backend/app/main.py` — **solo** gli endpoint `/admin/model-prices*` e `/admin/costs`
- `backend/tests/test_costs.py`
- `panel/src/Admin.jsx`, `panel/src/adminApi.js`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/handoff.md`

Fuori perimetro:
- `/admin/revenue` e la vista Ricavi
- azioni commerciali su Stripe (blocco 4), funnel di attivazione (blocco 5)
- helpdesk, inbox, analytics, gap KB, canali, plugin, API pubblica
