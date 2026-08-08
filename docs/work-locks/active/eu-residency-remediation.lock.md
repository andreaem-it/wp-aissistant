---
block: eu-residency-remediation
owner: codex
started_at: 2026-08-09T10:30:00+02:00
expires_at: 2026-08-11T10:30:00+02:00
branch: main
---

Obiettivo: spostare l'elaborazione backend in UE, rendere gli allegati R2 vincolati alla
jurisdiction UE e attivare retention e controlli production fail-closed senza interrompere il
servizio.

Perimetro previsto:
- configurazione live Railway del servizio `wp-aissistant`
- bucket R2 `wp-aissistant-attachments` e relativo Worker
- `cloudflare/attachment-storage/wrangler.jsonc`
- configurazione live `DATA_RETENTION_DAYS` e `STRICT_PRODUCTION_CONFIG`
- `docs/gdpr-eu-residency-audit.md`

Fuori perimetro:
- `panel/src/Admin.jsx`
- `backend/app/routers/admin.py`
- piani, prezzi e rimozione del piano gratuito
- sostituzione del provider AI, che richiede un blocco e una decisione architetturale separati
