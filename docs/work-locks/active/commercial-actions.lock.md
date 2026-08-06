---
block: commercial-actions
owner: claude
started_at: 2026-08-06T09:00:00+02:00
expires_at: 2026-08-07T09:00:00+02:00
branch: main
---

Obiettivo: il superadmin può agire commercialmente su un abbonamento — prolungare la prova,
applicare o togliere uno sconto, sospendere e riattivare, disdire — **passando da Stripe**, e
lasciando che sia il webhook ad aggiornare il database. Chiude anche il debito di
`set_client_plan`, che oggi scrive `plan_id` scavalcando Stripe.

Perimetro previsto:
- `backend/app/billing.py` — funzioni di azione su Stripe
- `backend/app/main.py` — **solo** `/admin/clients/{id}/plan` e i nuovi
  `/admin/clients/{id}/subscription/*`
- `backend/tests/test_billing.py`
- `panel/src/Admin.jsx`, `panel/src/adminApi.js`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/handoff.md`, `deploy/STRIPE.md`

Fuori perimetro:
- `/admin/revenue`, `/admin/costs` e i rispettivi listini (già rilasciati)
- funnel di attivazione e clienti a rischio (blocco 5)
- portale cliente e email di dunning (già rilasciati)
- helpdesk, inbox, analytics, canali, plugin, API pubblica
