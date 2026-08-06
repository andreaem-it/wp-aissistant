---
block: main-split-phase2
owner: claude
started_at: 2026-08-06T17:20:00+02:00
expires_at: 2026-08-07T17:20:00+02:00
branch: main
---

Obiettivo: **fase 2** della divisione di `main.py`. Estrarre l'area sviluppatori — chiavi API e
webhook in uscita — in `routers/developers.py`, e far salire in moduli neutri le tre utility
condivise che l'area usa. Nessun cambiamento osservabile: stessi path, metodi e risposte.

Perimetro previsto:
- `backend/app/util.py` (nuovo), `backend/app/deps.py`
- `backend/app/routers/developers.py` (nuovo)
- `backend/app/main.py` — rimozione delle parti spostate e registrazione del router
- `backend/tests/test_routes.py`
- `docs/handoff.md`

Fuori perimetro:
- `/v1` (API pubblica): dipende da helper ancora intrecciati, va in una fase sua
- tutte le altre aree, panel, plugin, worker
