---
block: billing-self-service
owner: claude
started_at: 2026-08-05T16:50:00+02:00
expires_at: 2026-08-06T16:50:00+02:00
branch: main
---

Obiettivo: il cliente gestisce da solo il proprio abbonamento senza scrivere al supporto —
portale Stripe (metodo di pagamento, fatture, cambio piano, disdetta), stato di fatturazione
visibile nel panel e email automatiche su pagamento fallito, trial in scadenza e cancellazione.

Perimetro previsto:
- `backend/app/billing.py`
- `backend/app/email.py`
- `backend/app/main.py` — **solo** gli endpoint `/billing/*` e `_usage`
- `backend/app/db.py` e nuova migrazione (campi abbonamento su `Client`)
- `backend/tests/test_billing.py`
- `panel/src/Profile.jsx`, `panel/src/api.js`, `panel/src/index.css`
- `README.md`, `docs/competitor-feature-backlog.md`

Fuori perimetro:
- helpdesk, inbox, analytics e gap KB
- canali email/WhatsApp/Messenger e relativi worker
- plugin WordPress e widget
- API pubblica `/v1`, webhook e workflow
- viste superadmin diverse da quelle commerciali (restano ai blocchi 2-5)
