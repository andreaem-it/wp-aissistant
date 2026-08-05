---
block: superadmin-revenue
owner: claude
started_at: 2026-08-05T17:35:00+02:00
expires_at: 2026-08-06T17:35:00+02:00
branch: main
---

Obiettivo: il superadmin risponde a «quanto fatturo?» — MRR/ARR ricostruiti dai piani e dagli
abbonamenti reali, ripartizione per piano, prove in scadenza, insoluti, disdette programmate e
churn mensile, con una vista dedicata nel panel admin.

Perimetro previsto:
- `backend/app/billing.py` — funzioni di calcolo dei ricavi
- `backend/app/main.py` — **solo** i nuovi endpoint `/admin/revenue*`
- `backend/tests/test_billing.py` (o nuovo `test_revenue.py`)
- `panel/src/Admin.jsx`, `panel/src/adminApi.js`, `panel/src/index.css`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/handoff.md`

Fuori perimetro:
- costi e margine per tenant da `AiResponseLog` (blocco 3, separato)
- azioni commerciali su Stripe: trial, coupon, sospensioni (blocco 4)
- funnel di attivazione e clienti a rischio (blocco 5)
- helpdesk, inbox, analytics, gap KB
- canali email/WhatsApp/Messenger e relativi worker
- plugin WordPress e widget
- API pubblica `/v1`, webhook e workflow
