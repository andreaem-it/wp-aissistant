---
block: meta-messaging-worker
owner: claude
started_at: 2026-08-05T00:05:00+02:00
expires_at: 2026-08-06T00:05:00+02:00
branch: worktree-sdk-npm-publishing
---

Obiettivo: creare il Worker Messenger/Instagram mancante. Il backend espone già inbound
(`/channels/meta/inbound`, allegati compresi) e outbound (`META_MESSAGING_OUTBOUND_URL`): manca
l'adapter che verifica la firma Meta, mappa pagina/account IG sul tenant, scarica gli allegati
e consegna le risposte dell'operatore.

Perimetro previsto:
- nuova cartella `cloudflare/meta-messaging-adapter/` (package.json, wrangler.jsonc,
  .gitignore, `src/index.js`, `src/protocol.js`, `src/media.js`, `test/*.test.js`)
- `.github/workflows/ci.yml` (nuovo job per questo Worker)
- `docs/meta-messaging-channel.md`
- `docs/competitor-feature-backlog.md` (solo la riga «Instagram/Facebook Messenger»)

Fuori perimetro:
- `backend/` per intero: i due contratti sono già rilasciati e non cambiano
- `panel/`, `sdk/`, `wp-plugin/`, `website/`
- gli altri Worker in `cloudflare/` (`whatsapp-adapter`, `email-router`, `attachment-storage`,
  `crm-adapter`)
- `docs/handoff.md`
