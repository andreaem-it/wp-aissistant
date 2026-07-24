=== WP AIssistant ===
Tags: ai, chatbot, customer-support, woocommerce, rag
Requires at least: 5.8
Tested up to: 6.5
Requires PHP: 7.4
Stable tag: 0.2.0
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

* Widget di chat flottante personalizzabile (titolo, avatar).
* Sincronizzazione automatica di pagine, articoli e prodotti WooCommerce alla pubblicazione.
* Pulsante di sincronizzazione completa per il primo caricamento / re-sync.
* Card prodotto WooCommerce (prezzo, immagine) direttamente in chat.
* Escalation a operatore umano quando serve.

Richiede un'istanza del backend WP AIssistant raggiungibile e una API Key del cliente.

== Installation ==

1. Carica la cartella `wp-aissistant` in `/wp-content/plugins/` (o installa lo zip da
   *Plugin → Aggiungi nuovo → Carica plugin*).
2. Attiva il plugin dalla schermata *Plugin*.
3. In *Impostazioni → WP AIssistant* imposta la tua **API Key**.
4. Usa **Sincronizza ora** per il primo caricamento della knowledge base.

== Changelog ==

= 0.2.0 =
* Il Backend URL non è più configurabile dall'utente: il plugin punta al backend
  hosted ufficiale. Resta configurabile solo l'API Key (oltre a titolo/immagine widget).

= 0.1.0 =
* Prima release: widget di chat flottante, sincronizzazione automatica dei contenuti
  (pagine, articoli, prodotti WooCommerce), info generali del sito, card prodotto ed
  escalation a operatore con ticket.
