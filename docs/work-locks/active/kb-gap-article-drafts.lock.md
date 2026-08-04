---
block: kb-gap-article-drafts
owner: codex
started_at: 2026-08-04T20:35:00+02:00
expires_at: 2026-08-05T20:35:00+02:00
branch: main
---

Obiettivo: generare, revisionare e pubblicare bozze di articoli Knowledge Base dai cluster di
gap più frequenti, con isolamento tenant, audit e verifica dell'impatto.

Perimetro previsto:
- `backend/app/analytics.py`
- `backend/app/main.py`
- `backend/app/db.py` e nuova migrazione, se necessaria
- `backend/tests/test_analytics.py`
- `panel/src/KnowledgeGaps.jsx`
- `panel/src/api.js`
- `docs/competitor-feature-backlog.md`
- `docs/handoff.md`

Fuori perimetro:
- plugin WordPress e widget
- sito marketing
- CRM, help desk e canali WhatsApp/Email/Messenger
- billing, onboarding e API pubblica
