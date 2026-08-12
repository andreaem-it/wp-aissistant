---
block: widget-extraction
owner: claude
started_at: 2026-08-12T16:45:00+02:00
expires_at: 2026-08-16T16:45:00+02:00
branch: main
---

Obiettivo: il widget esce da WordPress e diventa `sdk/widget`, un bundle framework-agnostic
configurato da un oggetto di opzioni. Il plugin smette di conoscere il widget e diventa un
produttore di opzioni più un adapter WooCommerce. Fase 1 di
`docs/embedded-assistant-roadmap.md`.

Criterio di fine, non negoziabile: **il plugin ricostruito si comporta esattamente come prima**,
carrello e order lookup inclusi. Un'estrazione che degrada una di quelle due è sbagliata, non
"quasi finita".

Metodo: spostare il codice **senza riscriverlo**, cambiando solo ciò che deve cambiare — i
globali `window.WPAI`, `window.WPAI_I18N`, `window.WPAI_RULES` diventano configurazione e
import. È lo stesso criterio della divisione di `main.py`: uno spostamento non cambia nulla di
osservabile.

Il vocabolario delle opzioni va dichiarato **una volta** in `sdk/widget/src/schema.js`: oggi
esiste solo in `wpai_sanitize_settings` (PHP), e la fase 3 aggiungerà un terzo produttore lato
pannello. Tre liste scritte a mano della stessa cosa sono il debito 5 daccapo.

Perimetro previsto:
- `sdk/widget/**` (nuovo: src, schema, build esbuild, test, package.json)
- `wp-plugin/wp-aissistant/assets/chat-widget.js`, `chat-i18n.js`, `chat-rules.js` (rimossi in
  favore del bundle) e `chat-widget.css`
- `wp-plugin/wp-aissistant/wp-aissistant.php` (produttore di opzioni + adapter host)
- `wp-plugin/build.sh`, `wp-plugin/tests/*.test.js`
- `.github/workflows/ci.yml` (build e test del bundle)
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro (liberi per un altro agente):
- `backend/`, `panel/`, `website/`, `cloudflare/`, `sdk/browser/`
- La pubblicazione su CDN (fase 2): qui il plugin carica l'artefatto dal proprio pacchetto
- Il configuratore nel pannello (fase 3)
