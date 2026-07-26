# Changelog

Tutte le modifiche rilevanti del plugin WP AIssistant.

## [0.4.0] - 2026-07-26

- Nuovo: streaming delle risposte AI via SSE (`POST /chat/stream`). Il widget renderizza
  i token man mano che arrivano (`sendMessageStream`), con rilevazione dell'escalation
  bufferizzando il prefisso `ESCALATE:` così una risposta parziale non viene mai mostrata.
  Fallback automatico al `POST /chat` bloccante se lo streaming fallisce prima di iniziare.

## [0.3.0] - 2026-07-26

- Nuovo: pulsanti di valutazione 👍/👎 sotto ogni risposta dell'assistente AI. Il
  voto viene inviato a `POST /chat/feedback` (autenticato con l'API Key del client,
  scoping per conversazione) e alimenta le statistiche di qualità nel pannello.

## [0.2.1] - 2026-07-24

- Fix: `sendMessage` non controllava `res.ok` prima di processare la risposta —
  un errore HTTP (es. `401 invalid api key`) veniva renderizzato come un fumetto
  assistente vuoto invece di mostrare un messaggio d'errore. Ora una risposta
  non-2xx fa fallire la promise e il gestore esistente mostra "Errore di
  connessione, riprova tra poco."; anche `conversation_id` non finisce più a
  `undefined` nel polling successivo.
- Fix: `#wpai-window` aveva `max-height` invece di `height` — la finestra si
  restringeva/allargava col contenuto anziché avere un'altezza fissa.

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
