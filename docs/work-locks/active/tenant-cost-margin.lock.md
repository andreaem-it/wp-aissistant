---
block: tenant-cost-margin
owner: claude
started_at: 2026-08-05T18:35:00+02:00
expires_at: 2026-08-06T18:35:00+02:00
branch: main
---

Obiettivo: sapere quanto costa servire ogni tenant e quale margine lascia. Listino prezzi per
modello gestito dal superadmin, costo calcolato dai token già registrati in `AiResponseLog`,
margine confrontato con il valore ricorrente del piano.

Perimetro previsto:
- `backend/app/costs.py` (nuovo)
- `backend/app/billing.py` — sola lettura di `monthly_value_cents`
- `backend/app/db.py` e migrazione `0047` (tabella listino prezzi)
- `backend/app/main.py` — **solo** i nuovi endpoint `/admin/costs` e `/admin/model-prices*`
- `backend/tests/test_costs.py` (nuovo)
- `panel/src/Admin.jsx`, `panel/src/adminApi.js`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/handoff.md`

Fuori perimetro:
- azioni commerciali su Stripe: trial, coupon, sospensioni (blocco 4)
- funnel di attivazione e clienti a rischio (blocco 5)
- `/admin/revenue` e la vista Ricavi già rilasciate
- helpdesk, inbox, analytics, gap KB
- canali email/WhatsApp/Messenger e relativi worker
- plugin WordPress e widget
