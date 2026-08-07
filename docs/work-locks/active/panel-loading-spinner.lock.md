---
block: panel-loading-spinner
owner: claude
started_at: 2026-08-07T23:30:00+02:00
expires_at: 2026-08-08T23:30:00+02:00
branch: main
---

Obiettivo: sostituire il testo «Caricamento…» con uno spinner, centrato quando blocca l'intera
vista e compatto quando sta dentro una scheda. Riusa `.wpai-spin` e l'icona già in uso in
`Upload.jsx`; sotto `prefers-reduced-motion` mostra il testo invece di un'icona ferma.

Perimetro previsto:
- `panel/src/Loading.jsx` (nuovo), `panel/src/index.css`
- le viste che oggi mostrano il testo: Admin, Settings, Developers, Leads, Automations,
  KnowledgeGaps, AnalyticsOverview, Conversations
- `docs/handoff.md` solo se serve

Fuori perimetro:
- backend, plugin, worker
- i messaggi che dicono *cosa* si sta caricando (anteprima allegato, upload): restano testo
