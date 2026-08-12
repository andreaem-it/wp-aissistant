---
block: widget-cdn-enable
owner: claude
started_at: 2026-08-13T00:55:00+02:00
expires_at: 2026-08-14T00:55:00+02:00
branch: main
---

Obiettivo: accendere il CDN nel plugin, ora che l'artefatto è pubblicato e verificato.

Verificato prima di accendere: `https://cdn.wpaissistant.it/widget/0.1.0/wpai-widget.js` risponde
`200` con `cache-control: public, max-age=31536000, immutable`, e l'impronta del file servito
coincide con l'SRI calcolata dalla build. Idem per il CSS e per `integrity.json`.

Perimetro previsto:
- `wp-plugin/wp-aissistant/wp-aissistant.php` (`WPAI_WIDGET_CDN`)
- `docs/embedded-assistant-roadmap.md`, `docs/competitor-feature-backlog.md`, `README.md`

Fuori perimetro: tutto il resto.
