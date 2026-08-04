---
block: inbound-channel-media
owner: claude
started_at: 2026-08-04T22:20:00+02:00
expires_at: 2026-08-05T22:20:00+02:00
branch: worktree-sdk-npm-publishing
---

Obiettivo: acquisire i media inbound dai canali (email, WhatsApp, Messenger/Instagram) come
allegati privati tenant-scoped nello storage R2 già esistente, e mostrare le immagini in
anteprima nell'inbox operatore senza esporre URL pubblici né token nella URL.

Perimetro previsto:
- `backend/app/attachments.py` (validazione e decodifica dei media inbound)
- `backend/app/main.py` (solo i tre endpoint `/channels/*/inbound` e gli helper allegati)
- `backend/tests/test_attachments.py`
- `backend/tests/test_email_channel.py`
- `backend/tests/test_whatsapp_channel.py`
- `backend/tests/test_meta_messaging_channel.py`
- `panel/src/Conversations.jsx`
- `panel/src/index.css`
- `docs/email-channel.md`, `docs/whatsapp-channel.md`, `docs/meta-messaging-channel.md`
- `docs/competitor-feature-backlog.md` (solo la riga «Allegati conversazione»)

Non servono migrazioni: il modello `Attachment` copre già i campi necessari, quindi
`backend/app/db.py` e `backend/alembic/` restano liberi.

Fuori perimetro:
- `backend/app/db.py`, `backend/alembic/`
- `backend/app/analytics.py`, `rag.py`, `billing.py`, `workflows.py`, `crm.py`, `helpdesk.py`
- `panel/src/*` a parte `Conversations.jsx` e `index.css`
- `sdk/`, `wp-plugin/`, `cloudflare/`, `website/`
- `docs/handoff.md`
