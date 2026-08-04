# @wp-aissistant/browser

SDK browser headless di **WP AIssistant**: il motore conversazionale (chat RAG ancorata ai
contenuti del sito, streaming, escalation, ticket, CSAT e lead form) senza imporre il widget
WordPress. Pensato per siti custom, shop headless e applicazioni che disegnano la propria
interfaccia.

- ESM puro, nessuna dipendenza, nessuno step di build.
- Sessione persistente: la conversazione riprende dopo refresh e navigazione.
- Il token privato della conversazione non compare mai nella URL.
- Web component `<wpai-chat>` isolato in Shadow DOM se serve un'interfaccia pronta.

## Installazione

```sh
npm install @wp-aissistant/browser
```

Senza bundler, direttamente da CDN:

```html
<script type="module">
  import { createClient } from "https://esm.sh/@wp-aissistant/browser";
</script>
```

## Uso

```js
import { createClient } from "@wp-aissistant/browser";

const assistant = createClient({
  apiBase: "https://backend.wpaissistant.it",
  apiKey: "CHIAVE_PUBBLICA_WIDGET",
});

const result = await assistant.send("Avete questo prodotto in blu?", {
  locale: "it-IT",
  supportAvailable: true,
});
console.log(result.reply, result.products);

for await (const event of assistant.stream("Mostrami le alternative")) {
  if (event.type === "token") output.textContent += event.text;
}
```

### API del client

| Metodo | Cosa fa |
|---|---|
| `send(message, options)` | Invia un messaggio e restituisce la risposta completa. |
| `stream(message, options)` | Async iterator sugli eventi SSE: `start`, `token`, `escalated`, `ticket_offered`, `quota_exceeded`, `done`. |
| `messages({ afterId, limit })` | Polling dei messaggi, incluse le risposte dell'operatore. |
| `feedback(messageId, "up" \| "down")` | Voto su una singola risposta dell'assistente. |
| `contact(email, url)` | Lascia un recapito durante l'escalation. |
| `ticket(reason)` | Apre una richiesta quando il supporto umano è chiuso. |
| `rating(score, comment)` | CSAT di fine conversazione (1–5). |
| `leadForm(trigger)` / `submitLead(formId, data, consent)` | Form di lead capture configurato dal tenant. |
| `session` / `reset()` | Stato della sessione e cancellazione locale. |

Opzioni del costruttore: `apiBase`, `apiKey`, `storage`, `storagePrefix`, `fetchImpl`,
`timeout`. Gli errori applicativi sono istanze di `WpAissistantError` con `status` e `payload`
(`status` vale `0` per timeout e problemi di rete).

I tipi TypeScript sono inclusi nel pacchetto: nessun `@types/*` da installare.

## Web component

```js
import { registerWpAissistantChat } from "@wp-aissistant/browser/widget";
registerWpAissistantChat();
```

```html
<wpai-chat
  api-base="https://backend.wpaissistant.it"
  api-key="CHIAVE_PUBBLICA_WIDGET"
  title="Come possiamo aiutarti?"
  privacy-url="https://esempio.it/privacy"
></wpai-chat>
```

L'elemento emette `wpai-event` per ogni evento di streaming e `wpai-error` in caso di errore.

## Sicurezza

- `apiKey` è la chiave **pubblica** del widget: non deve avere scope operatore o canale.
- In produzione `apiBase` deve usare HTTPS; il client rifiuta HTTP fuori da `localhost`.
- Renderizza ogni testo come contenuto, mai come HTML, e applica la tua Content Security Policy.

## Compatibilità

Browser con `fetch`, `AbortController` e `ReadableStream`; Node.js ≥ 18 per test e SSR.

Documentazione completa: [`docs/browser-sdk.md`](https://github.com/andreaem-it/wp-aissistant/blob/main/docs/browser-sdk.md).
