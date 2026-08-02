# Changelog

Tutte le modifiche rilevanti del plugin WP AIssistant.

## [1.1.9] - 2026-08-02

- Aggiunti A/B test per i messaggi proattivi, con assegnazione stabile per visitatore.
- Visualizzazioni, chat aperte e conversione sono misurate separatamente per variante.

## [1.1.8] - 2026-08-02

- Sincronizzazione automatica di giorni, fascia oraria e fuso WordPress con il calendario SLA.
- Registrazione dell’installazione mediante challenge HMAC sul dominio autorizzato.
- Credenziale di sincronizzazione privata e distinta dalla API Key pubblica del widget.

## [1.1.3] - 2026-07-30

- L'offerta di ticket è ora legata esclusivamente al turno che ha richiesto l'escalation.
- Le offerte obsolete vengono rimosse e un nuovo messaggio normale chiude la card.
- Testo della card reso contestuale alla richiesta che necessita un operatore.

## [1.1.2] - 2026-07-30

- Aggiornamento immediato dei fragment WooCommerce e dei mini-carrelli del tema.

## [1.1.1] - 2026-07-30

- Aggiunta un'azione WooCommerce verificata nelle card prodotto.
- Impedite conferme non verificate su carrello, checkout, coupon e totale.
- I prodotti variabili, raggruppati ed esterni richiedono la selezione nella pagina prodotto.

## [1.1.0] - 2026-07-30

- Aggiunta in wp-admin la configurazione della disponibilità del supporto umano:
  attivazione, giorni della settimana e orario di inizio/fine nel fuso WordPress.
- Il widget calcola la disponibilità lato browser, gestendo anche turni notturni che
  attraversano la mezzanotte.
- Fuori orario un'escalation non apre più automaticamente una conversazione live:
  mostra una card che permette al visitatore di aprire volontariamente un ticket.
- La proposta di ticket persiste durante refresh e navigazione; dopo l'apertura viene
  raccolta l'email per notificare la risposta dell'operatore.
- Aggiunta un'informativa AI personalizzabile, centrata prima del messaggio iniziale.
  L'accettazione della Privacy Policy è stata spostata nello stesso testo e rimossa
  dalla zona sotto il campo di scrittura.

## [1.0.1] - 2026-07-30

- Il widget ricarica lo storico della conversazione esistente dal backend e riprende
  immediatamente il polling quando l'utente aggiorna la pagina o naviga nel sito.
- Lo stato aperto/chiuso della chat viene mantenuto in `localStorage`.
- Rimosso il secondo focus ring applicato direttamente all'input: resta quello accessibile
  e correttamente allineato del contenitore del composer.

## [1.0.0] - 2026-07-30

- Widget completamente ridisegnato: animazioni di apertura e dei messaggi, typing indicator
  animato, launcher esteso opzionale, micro-interazioni e layout mobile full-screen.
- Nuove opzioni: colore principale, tema chiaro/scuro/automatico, posizione, intensità
  delle animazioni, sottotitolo, messaggio di benvenuto ed etichetta del launcher.
- Pagine wp-admin riprogettate con card, gerarchia visiva moderna, anteprima live,
  riepilogo utilizzo e una pagina sincronizzazione più chiara.
- Migliorata l'accessibilità con focus visibile, chiusura via Esc, stato ARIA, dialog
  semantico, regione live e supporto completo a `prefers-reduced-motion`.
- Il markup contenente titolo, avatar e testi configurabili non usa più template HTML:
  tutti i nodi sono creati via DOM e i valori sono assegnati con `textContent`.

## [0.9.2] - 2026-07-29

- Fix (sicurezza, critico): la API Key pubblica del widget non autorizza più da sola
  lettura, prosecuzione o modifica di qualsiasi conversazione del tenant. Ogni nuova
  conversazione riceve un token casuale separato; il widget lo conserva e lo presenta
  per chat, polling, feedback e contatto. Il backend salva soltanto l'hash del token.
- Le conversazioni create con versioni precedenti vengono abbandonate in sicurezza e
  ricreate automaticamente al primo nuovo messaggio.

## [0.9.1] - 2026-07-27

- Fix (sicurezza, critico): `wpai_user_token` (che sblocca i dati completi dell'ordine)
  era firmato in HMAC con l'`api_key`, che è pubblica (localizzata nel JS del widget) →
  un attaccante poteva forgiare un token per qualsiasi `user_id` e leggere dati completi
  di ordini altrui. Ora firmato con `wp_salt('auth')` (segreto server-side, `wpai_token_secret`).

## [0.9.0] - 2026-07-27

- Nuovo (GDPR): impostazione "URL Privacy Policy". Se impostata, il widget mostra in
  fondo un avviso "Continuando accetti la privacy policy" con link (costruito via DOM,
  href limitato a http(s)). Passata al widget come `WPAI.privacyUrl`.

## [0.8.1] - 2026-07-27

- Fix (sicurezza): le card prodotto nel widget sono costruite via DOM (`textContent`)
  invece di `innerHTML` — elimina un possibile XSS se titolo/prezzo di un prodotto
  contenessero HTML. Gli URL di prodotto/immagine sono limitati a http(s).

## [0.8.0] - 2026-07-27

- Nuovo: lookup ordine WooCommerce in chat. Nuova rotta REST `wpai/v1/order-lookup`
  (autenticata con l'api_key del client, riusata come segreto condiviso col backend) che
  restituisce stato + data spedizione per un visitatore anonimo verificato (numero ordine +
  email/cognome), o i dettagli completi se il visitatore è loggato e proprietario
  dell'ordine (token firmato HMAC a scadenza breve, `wp_ajax_wpai_user_token`).
- Backend: nuovo marcatore testuale `ORDER_LOOKUP:` (stesso pattern di `ESCALATE:`) — il
  modello raccoglie numero ordine + identificativo conversando, poi il backend richiama il
  plugin e genera la risposta da template deterministico (mai una seconda chiamata al
  modello per i dati dell'ordine, per evitare allucinazioni su dati finanziari).

## [0.7.1] - 2026-07-27

- Sostituite tutte le emoji con icone reali (Font Awesome Free, via CDN cdnjs con SRI):
  pulsante flottante, feedback 👍/👎, conferma email, stato sincronizzazione nella pagina
  Sincronizzazione (`assets/admin-sync.js`, ora costruito via DOM invece di `textContent`
  per non introdurre un rischio XSS quando lo stato include un messaggio d'errore del backend).

## [0.7.0] - 2026-07-26

- Overhaul admin: menu top-level "AI Assistant" (`add_menu_page`, fuori da Impostazioni)
  con due sottopagine — **Impostazioni** (API Key, widget, + **piano e uso mensile** via
  `GET /usage`) e **Sincronizzazione**.
- Sync in tempo reale: la pagina Sincronizzazione ora è guidata via AJAX
  (`assets/admin-sync.js`), item-by-item. Nuovi handler `wp_ajax_wpai_sync_list`,
  `wpai_sync_item` (push bloccante → job_id), `wpai_job_status` (proxy a
  `/ingest/jobs/{id}`). Ogni riga mostra invio → elaborazione → sincronizzato.
- Refactor `wpai_backend_post($path,$payload,$blocking)`; l'auto-sync su `save_post`
  resta fire-and-forget.

## [0.6.1] - 2026-07-26

- Nuovo: gestione dello stato/evento `quota_exceeded` — il widget mostra un messaggio
  quando è stata raggiunta la quota mensile di messaggi del piano.

## [0.6.0] - 2026-07-26

- Nuovo: indicatore "<nome operatore> sta scrivendo…" nel widget (dal polling di
  `/conversations/{id}/messages`, campo `operator_typing`). Poll widget a 3s.

## [0.5.2] - 2026-07-26

- Fix: nessun indicatore "sta scrivendo" quando la conversazione è escalata a un
  operatore (helper `isEscalated`); il messaggio del cliente va all'operatore senza
  fingere una risposta AI.

## [0.5.1] - 2026-07-26

- Fix: auto-recovery su 404. Un `wpai_conversation_id` in localStorage non più valido
  (es. dopo cambio api_key/client) faceva 404 e bloccava il widget; ora `sendMessage` e
  `sendMessageStream` azzerano l'id e riprovano una volta da conversazione nuova.

## [0.5.0] - 2026-07-26

- Nuovo: alla escalation il widget mostra un campo email; il visitatore può lasciarla
  (`POST /chat/contact`, con l'URL della pagina) per ricevere una notifica via email
  quando l'operatore risponde. Mostrato una volta per conversazione.

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
