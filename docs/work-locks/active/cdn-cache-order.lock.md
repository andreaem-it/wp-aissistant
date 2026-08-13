---
block: cdn-cache-order
owner: claude
started_at: 2026-08-13T05:30:00+02:00
expires_at: 2026-08-14T05:30:00+02:00
branch: main
---

Obiettivo: mettere per iscritto l'ordine delle operazioni sul CDN, e far fallire il workflow
prima di pubblicare se la regola CORS non c'è.

Il difetto: la regola CORS è stata applicata **dopo** la prima pubblicazione. Le risposte già in
cache al bordo erano state salvate senza `Access-Control-Allow-Origin` e senza `Vary: Origin`, e
con `Cache-Control: immutable, max-age=31536000` resterebbero lì un anno. Un'origine mai vista
prima riceve la risposta giusta; quella che aveva già chiesto il file resta avvelenata — cioè
esattamente il nostro sito, il primo ad averlo caricato.

Perimetro previsto:
- `.github/workflows/publish-widget.yml` (CORS verificata **prima** del `put`)
- `cloudflare/cdn/README.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro: tutto il resto.
