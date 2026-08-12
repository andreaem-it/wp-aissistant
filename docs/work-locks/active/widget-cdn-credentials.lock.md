---
block: widget-cdn-credentials
owner: claude
started_at: 2026-08-13T00:40:00+02:00
expires_at: 2026-08-14T00:40:00+02:00
branch: main
---

Obiettivo: il workflow di pubblicazione del widget verifica che il token R2 funzioni davvero,
invece di scoprirlo al primo tag. Coda del blocco `widget-cdn`.

Il caso da coprire: un token creato con i permessi di Pages invece che con
`Workers R2 Storage: Edit` supera ogni controllo di configurazione — il segreto esiste, il
workflow parte — e fallisce solo al momento del `put`, cioè quando si sta già pubblicando una
versione.

Perimetro previsto:
- `.github/workflows/publish-widget.yml`

Fuori perimetro: tutto il resto.
