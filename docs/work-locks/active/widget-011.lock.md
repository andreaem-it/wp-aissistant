---
block: widget-011
owner: claude
started_at: 2026-08-13T06:00:00+02:00
expires_at: 2026-08-14T06:00:00+02:00
branch: main
---

Obiettivo: pubblicare il widget 0.1.1 e spostarci il sito.

Perché una versione nuova invece di svuotare la cache: la 0.1.0 è stata salvata al bordo prima
che il bucket avesse la regola CORS, e con `immutable` più un anno di `max-age` quella risposta
resta. Un percorso mai chiesto prima non ha niente in cache e nasce con le intestazioni giuste —
senza dashboard, senza credenziali, e passando dal workflow che ora verifica la regola CORS prima
di pubblicare. È anche la prova che la pipeline funziona da capo a fondo.

Il codice non cambia: cambia solo il numero di versione, quindi l'impronta SRI resta la stessa.

Perimetro previsto:
- `sdk/widget/package.json` (versione)
- `website/index.html` (percorso della versione)
- `docs/embedded-assistant-roadmap.md`

Fuori perimetro: tutto il resto.
