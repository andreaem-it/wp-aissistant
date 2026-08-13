---
block: cdn-cors
owner: claude
started_at: 2026-08-13T04:10:00+02:00
expires_at: 2026-08-14T04:10:00+02:00
branch: main
---

Obiettivo: il widget servito dal CDN si carica davvero in un browser.

Il difetto, trovato guardando il nostro sito con un browser vero: il tag porta `integrity` e
quindi **deve** portare `crossorigin="anonymous"`, e un fetch in modalità CORS pretende
`Access-Control-Allow-Origin` sulla risposta. R2 non lo manda di default, quindi il browser
scarica il file e lo scarta. Il widget non compariva, senza che nulla fallisse lato server: il
`put` era andato, l'URL rispondeva `200`, l'impronta coincideva.

È esattamente il fallimento che il passo «verify it is publicly reachable» del workflow non può
vedere, perché `curl` non fa CORS. Va aggiunto un controllo che lo faccia.

Perimetro previsto:
- `.github/workflows/publish-widget.yml` (verifica CORS)
- `docs/embedded-assistant-roadmap.md`, `sdk/widget/README.md`

Fuori perimetro: tutto il resto. La regola CORS sul bucket è configurazione dell'account
Cloudflare, non codice.
