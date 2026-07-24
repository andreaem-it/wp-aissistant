# Changelog

Tutte le modifiche rilevanti del plugin WP AIssistant.

## [0.2.0] - 2026-07-24

- Il Backend URL non è più un campo di impostazione: il plugin punta al backend
  hosted ufficiale (`WPAI_BACKEND_URL`, hardcoded). Restano configurabili solo API
  Key, titolo e immagine del widget. Per test/staging, override definendo
  `WPAI_BACKEND_URL` in `wp-config.php` prima del caricamento del plugin.
- Rimosso l'header `ngrok-skip-browser-warning` dal widget (era solo per i test
  tramite tunnel ngrok in fase di sviluppo).

## [0.1.0] - 2026-07-23

Prima versione.

- Floating chat widget con header configurabile (titolo + immagine), indicatore
  "sta scrivendo...", card prodotto (immagine/titolo/prezzo) nei suggerimenti.
- Polling messaggi per ricevere le risposte dell'operatore senza ricaricare la pagina.
- Sync automatico di post/pagine/prodotti WooCommerce alla pubblicazione, più un
  documento sintetico con le informazioni generali del sito.
- Pulsante "Sincronizza ora" per il primo caricamento o un re-sync completo.
- Autenticazione via `Authorization: Bearer` verso il backend.
