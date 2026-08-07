=== WP AIssistant ===
Tags: ai, chatbot, customer-support, woocommerce, rag
Requires at least: 5.8
Tested up to: 6.5
Requires PHP: 7.4
Stable tag: 1.2.3
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Assistente AI di supporto clienti: risponde ai visitatori con i contenuti del sito e passa la
parola a un operatore quando serve.

== Description ==

WP AIssistant aggiunge un widget di chat flottante al tuo sito WordPress / WooCommerce. Le
risposte sono generate da un backend RAG a partire dai contenuti che pubblichi; quando una
richiesta esce dal perimetro dell'AI (rimborsi, reclami, domande fuori contesto) la
conversazione viene inoltrata a un operatore umano tramite ticket.

Funzionalità principali:

* Widget personalizzabile con identità, colore, tema, posizione, animazioni e preset per pulsante e finestra.
* Anteprima live nel pannello amministrativo.
* Sincronizzazione automatica di pagine, articoli e prodotti WooCommerce alla pubblicazione.
* Pulsante di sincronizzazione completa per il primo caricamento / re-sync.
* Card prodotto WooCommerce (prezzo, immagine) direttamente in chat.
* Escalation a operatore umano quando serve.

Richiede un'istanza del backend WP AIssistant raggiungibile e una API Key del cliente.

== Installation ==

1. Carica la cartella `wp-aissistant` in `/wp-content/plugins/` (o installa lo zip da
   *Plugin → Aggiungi nuovo → Carica plugin*).
2. Attiva il plugin dalla schermata *Plugin*.
3. Nel menu *AI Assistant → Impostazioni* imposta la tua **API Key** (lì vedi anche piano e uso).
4. In *AI Assistant → Sincronizzazione* usa **Sincronizza ora** per il primo caricamento.

== Changelog ==

= 1.2.3 =
* Regole di orario e messaggi proattivi in un file separato, con test automatici.

= 1.2.0 =
* Impostazioni organizzate nelle schede Generali, Aspetto, Operatori e Info e supporto.
* Nuovi stili per launcher, finestra e dimensioni del widget con anteprima live.
* Verifica licenza con piano, stato e scadenza/rinnovo dell'abbonamento.
* Esportazione diagnostica JSON senza API Key o segreti.

= 1.1.8 =
* Gli orari del supporto e il fuso WordPress vengono sincronizzati automaticamente con il backend.
* La sincronizzazione usa una credenziale privata dell’installazione verificata con challenge HMAC; la API Key pubblica non può modificare le impostazioni SLA.

= 1.1.3 =
* Corretto: l'offerta di ticket appare soltanto in seguito a un'escalation e sparisce se la conversazione prosegue normalmente.
* Migliorato: il testo dell'avviso chiarisce che è la richiesta corrente a richiedere un operatore.

= 1.1.2 =
* Corretto: il mini-carrello e il contatore del tema si aggiornano subito dopo l'aggiunta dalla chat.

= 1.1.1 =
* Corretto: l'assistente non dichiara più modifiche al carrello che non sono avvenute.
* Nuovo: le schede prodotto aggiungono realmente gli articoli semplici al carrello WooCommerce.
* Nuovo: i prodotti con varianti rimandano alla selezione delle opzioni.

= 1.1.0 =
* Nuovi orari del supporto umano configurabili per giorni e fascia oraria, nel fuso
  orario impostato in WordPress.
* Fuori orario il widget non effettua un passaggio live automatico: propone invece
  l'apertura esplicita di un ticket asincrono con notifica email.
* Nuova informativa AI personalizzabile mostrata prima della conversazione; nello stesso
  punto viene mostrato anche il link alla Privacy Policy.

= 1.0.1 =
* La cronologia della conversazione viene ripristinata navigando tra le pagine o
  aggiornando il browser; viene mantenuto anche lo stato aperto/chiuso del widget.
* Corretto il doppio contorno di focus visibile dentro il campo messaggio.

= 1.0.0 =
* Nuovo widget 2026: animazioni fluide, apertura accessibile, tema chiaro/scuro/automatico,
  colore brand, posizione, etichetta launcher, sottotitolo e messaggio di benvenuto.
* Nuovo pannello amministrativo a card con anteprima live e flusso di configurazione guidato.
* Accessibilità: navigazione da tastiera, chiusura con Esc, aria-live e rispetto di
  prefers-reduced-motion.
* Sicurezza: il markup configurabile del widget viene ora costruito interamente via DOM.

= 0.9.2 =
* Fix (sicurezza): ogni conversazione del visitatore è protetta da un token casuale
  separato dalla API Key pubblica del widget. Il token è richiesto per continuare o
  leggere la chat, inviare feedback e salvare il contatto; sul backend resta solo l'hash.

= 0.9.1 =
* Fix (sicurezza): il token identità per il lookup ordini (che sblocca i dati completi)
  ora è firmato con un segreto server-side (wp_salt) e non più con l'API Key — l'API Key
  è pubblica nel widget, quindi era falsificabile. I token già emessi (validità 5 min)
  vanno rigenerati automaticamente.

= 0.9.0 =
* Nuovo (GDPR): campo "URL Privacy Policy" nelle impostazioni; se impostato il widget
  mostra un avviso "Continuando accetti la privacy policy" con il link.

= 0.8.1 =
* Fix (sicurezza): card prodotto costruite via DOM invece di innerHTML (elimina un
  possibile XSS); URL prodotto/immagine limitati a http(s).

= 0.8.0 =
* Nuovo: l'assistente può rispondere a domande sullo stato di un ordine WooCommerce
  direttamente in chat. Chiede numero d'ordine + email/cognome per verificare l'identità
  (visitatori anonimi vedono solo stato e data di spedizione); gli utenti loggati, se
  proprietari dell'ordine, vedono i dettagli completi.

= 0.7.1 =
* Sostituite le emoji con icone reali (Font Awesome) nel widget e nelle pagine di
  amministrazione del plugin.

= 0.7.0 =
* Nuovo: menu dedicato "AI Assistant" (fuori da Impostazioni), con pagine separate
  Impostazioni e Sincronizzazione.
* Nuovo: in Impostazioni ora si vede il piano e l'uso mensile (messaggi usati / limite).
* Nuovo: sincronizzazione in tempo reale — ogni contenuto/prodotto mostra il proprio
  stato (invio → elaborazione → sincronizzato) man mano che procede.

= 0.6.1 =
* Nuovo: messaggio chiaro nel widget quando viene raggiunto il limite mensile di
  messaggi del piano.

= 0.6.0 =
* Nuovo: quando un operatore umano sta scrivendo la risposta, il widget mostra
  "<nome operatore> sta scrivendo…".

= 0.5.2 =
* Fix: quando la conversazione è già stata passata a un operatore, inviando un nuovo
  messaggio non appare più il fuorviante "sta scrivendo..." (nessuna AI sta rispondendo).

= 0.5.1 =
* Fix: se l'ID conversazione salvato non è più valido (es. dopo un cambio di API Key/
  client), il widget riceveva 404 e restava bloccato. Ora azzera l'ID e riparte da una
  nuova conversazione automaticamente.

= 0.5.0 =
* Nuovo: quando la richiesta passa a un operatore, il visitatore può lasciare la sua
  email per essere avvisato via email appena arriva la risposta.

= 0.4.0 =
* Nuovo: le risposte dell'assistente AI ora compaiono in streaming, parola per parola,
  invece di apparire tutte insieme dopo l'attesa. Fallback automatico alla modalità
  classica se lo streaming non è disponibile.

= 0.3.0 =
* Nuovo: valutazione 👍/👎 sotto ogni risposta dell'assistente AI, così i visitatori
  possono segnalare se una risposta è stata utile (alimenta le statistiche di qualità).

= 0.2.1 =
* Fix: una risposta di errore dal backend (es. API Key non valida) veniva mostrata
  come un fumetto vuoto invece di un messaggio d'errore leggibile.
* Fix: finestra della chat ora ad altezza fissa invece di adattarsi al contenuto.

= 0.2.0 =
* Il Backend URL non è più configurabile dall'utente: il plugin punta al backend
  hosted ufficiale. Resta configurabile solo l'API Key (oltre a titolo/immagine widget).

= 0.1.0 =
* Prima release: widget di chat flottante, sincronizzazione automatica dei contenuti
  (pagine, articoli, prodotti WooCommerce), info generali del sito, card prodotto ed
  escalation a operatore con ticket.
