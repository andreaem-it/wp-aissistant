---
block: main-split-phase1
owner: claude
started_at: 2026-08-06T16:30:00+02:00
expires_at: 2026-08-07T16:30:00+02:00
branch: main
---

Obiettivo: **fase 1** della divisione di `main.py` (8016 righe, 182 endpoint). Estrarre le
fondamenta condivise in `app/deps.py` e spostare la prima area — billing e viste commerciali
del superadmin — in un `APIRouter`, senza alcun cambiamento di comportamento: stessi path,
stessi metodi, stesse risposte, stessa suite verde.

Lo scopo è deliberatamente ristretto: il valore di questo blocco è **stabilire il modello** e
dimostrarlo su un'area, non svuotare il file. Le fasi successive spostano un'area alla volta.

Perimetro previsto:
- `backend/app/deps.py` (nuovo)
- `backend/app/routers/__init__.py`, `backend/app/routers/commercial.py` (nuovi)
- `backend/app/main.py` — rimozione delle parti spostate e registrazione del router
- `docs/handoff.md` — modello e ordine delle fasi rimanenti

Fuori perimetro:
- qualunque modifica funzionale: se cambia una risposta, è un errore, non un miglioramento
- le altre aree di `main.py` (helpdesk, canali, widget, analytics, API pubblica): fasi successive
- panel, plugin, worker Cloudflare
