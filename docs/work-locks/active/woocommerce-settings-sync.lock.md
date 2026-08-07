---
block: woocommerce-settings-sync
owner: claude
started_at: 2026-08-08T10:00:00+02:00
expires_at: 2026-08-09T10:00:00+02:00
branch: main
---

Obiettivo: portare nella knowledge base le impostazioni WooCommerce di **spedizione e pagamento**,
che sono la fonte autorevole per le domande a cui il modello stava rispondendo inventando. Il
plugin legge zone/metodi e gateway abilitati e li invia strutturati; il backend li rende in testo
e li indicizza come sorgente `woocommerce`, sostituendo la versione precedente a ogni sync.

Perimetro previsto:
- `backend/app/routers/knowledge.py` (nuovo endpoint), `backend/app/worker.py` (nuovo tipo di job)
- `backend/app/rag.py` solo se serve per la resa del testo
- `backend/tests/test_woocommerce_settings.py` (nuovo)
- `wp-plugin/wp-aissistant/wp-aissistant.php`, `assets/admin-sync.js` se serve
- `panel/src/Upload.jsx` per l'etichetta della sorgente
- `README.md`, `CHANGELOG.md`, `readme.txt`, `docs/handoff.md`

Fuori perimetro:
- soglia di scope e reranking: non si toccano senza i dati del debug
- altri canali e aree del backend
