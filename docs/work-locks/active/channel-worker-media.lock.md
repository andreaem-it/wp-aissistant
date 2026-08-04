---
block: channel-worker-media
owner: claude
started_at: 2026-08-04T22:52:00+02:00
expires_at: 2026-08-05T22:52:00+02:00
branch: worktree-sdk-npm-publishing
---

Obiettivo: far scaricare e inoltrare davvero i media ai Worker dei canali, completando il
contratto `attachments` rilasciato nel blocco `inbound-channel-media`. Il Worker WhatsApp
risolve il media id con il token del tenant e inoltra i byte; l'email router estrae gli
allegati MIME e smette di rifiutare le email con solo allegati. Entrambi troncano ai limiti
del backend invece di far rifiutare l'intero messaggio.

Perimetro previsto:
- `cloudflare/whatsapp-adapter/src/index.js`, `src/protocol.js`, nuovo `src/media.js`
- `cloudflare/whatsapp-adapter/test/*.test.js`
- `cloudflare/email-router/src/index.js`, nuovo `src/attachments.js`
- `cloudflare/email-router/test/*.test.js`
- `.github/workflows/ci.yml` (nuovo job per l'email router, che oggi non è in CI)
- `docs/whatsapp-channel.md`, `docs/email-channel.md`
- `docs/competitor-feature-backlog.md` (solo la riga «Allegati conversazione»)

Fuori perimetro:
- `backend/` per intero: il contratto inbound è già rilasciato e non cambia
- `panel/`, `sdk/`, `wp-plugin/`, `website/`
- `cloudflare/attachment-storage`, `cloudflare/crm-adapter`
- `docs/handoff.md`
