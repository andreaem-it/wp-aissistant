---
block: widget-configurator
owner: claude
started_at: 2026-08-13T01:15:00+02:00
expires_at: 2026-08-16T01:15:00+02:00
branch: main
---

Obiettivo: la schermata di installazione nel pannello. Il cliente sceglie fra **plugin
WordPress** e **integrazione JavaScript**; se sceglie la seconda configura l'aspetto e riceve lo
snippet già personalizzato. Metà frontend della fase 3 di `docs/embedded-assistant-roadmap.md`.

Il backend che serve c'è già (blocco `widget-config-server`): `GET`/`PUT /account/widget-config`
restituisce configurazione **e vocabolario**, così il pannello costruisce i controlli da lì
invece di riscrivere la lista dei valori ammessi — sarebbe la terza copia della stessa cosa.

L'anteprima monta il **widget vero**, non un facsimile: è l'argomento per cui questa fase viene
dopo l'estrazione. Serve però una modalità che non invii niente — un'anteprima che apre
conversazioni vere sporcherebbe l'inbox e le statistiche del cliente ogni volta che qualcuno
guarda la schermata.

Perimetro previsto:
- `panel/src/Install.jsx`, `panel/src/snippet.js` (+ test), `panel/src/api.js`
- `panel/src/Settings.jsx` o `App.jsx` (dove vive la schermata)
- `panel/package.json` (dipendenza `file:` verso `sdk/widget`)
- `sdk/widget/src/widget.js`, `src/index.js`, `package.json` (modalità anteprima ed export)
- `sdk/widget/test/`
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro (liberi per un altro agente):
- `backend/` — gli endpoint esistono e non cambiano
- `wp-plugin/`, `website/`, `cloudflare/`, `sdk/browser/`
- La sorgente di verità fra pannello e pagina del plugin per i clienti WordPress: è una
  decisione scritta nella roadmap e non eseguita qui
