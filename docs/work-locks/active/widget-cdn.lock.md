---
block: widget-cdn
owner: claude
started_at: 2026-08-13T00:15:00+02:00
expires_at: 2026-08-16T00:15:00+02:00
branch: main
---

Obiettivo: il widget si pubblica su R2 con percorsi **versionati e immutabili**, SRI calcolata e
dichiarata, e il plugin lo carica dal CDN con ripiego sulla copia nel proprio pacchetto. Fase 2
di `docs/embedded-assistant-roadmap.md`.

Perché R2 e non Pages, visto che Pages è già in uso per sito e pannello: `pages deploy` pubblica
*il sito corrente* e sostituisce la produzione, mentre qui servono versioni che restano vive per
anni — il plugin pinna una versione con SRI e i siti dei clienti non aggiornano. Su R2 un `put`
aggiunge senza togliere, che è la semantica di un artefatto immutabile.

Stato dell'infrastruttura al momento del lock, verificato:
- bucket `wp-aissistant-cdn` creato;
- `cdn.wpaissistant.it` risolve su Cloudflare ma **non è collegato al bucket** — risponde `404`
  con l'HTML di un progetto Pages, non con l'errore XML di R2;
- il token con permesso di scrittura su R2 non è ancora fra i segreti del repository.

Questo blocco prepara tutto ciò che non dipende da quei due punti. La pubblicazione vera resta
disattivata finché non ci sono: il workflow non deve fingere di aver pubblicato.

Perimetro previsto:
- `sdk/widget/build.mjs` (SRI calcolata insieme al bundle)
- `.github/workflows/publish-widget.yml` (nuovo, su tag `widget-v*`)
- `wp-plugin/wp-aissistant/wp-aissistant.php` (caricamento dal CDN con ripiego locale)
- `sdk/widget/test/`, `wp-plugin/build.sh`
- `README.md`, `sdk/widget/README.md`, `docs/embedded-assistant-roadmap.md`,
  `docs/competitor-feature-backlog.md`

Fuori perimetro (liberi per un altro agente):
- `backend/`, `panel/`, `website/`
- Il configuratore nel pannello (metà frontend della fase 3)
- La creazione del dominio personalizzato e del token: sono operazioni sull'account Cloudflare
