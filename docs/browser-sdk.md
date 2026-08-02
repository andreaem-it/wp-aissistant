# SDK browser headless

`sdk/browser` espone il motore conversazionale senza imporre il widget WordPress. È pensato per
siti custom, shop headless e applicazioni che vogliono disegnare autonomamente l'interfaccia.

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

La sessione viene conservata in `localStorage` e ripresa alla navigazione successiva. Il token
privato della conversazione non compare mai nella URL: viene inviato nel body o nell'header
`X-Conversation-Token`. Sono disponibili `messages`, `feedback`, `contact`, `ticket`, `rating`,
`stream`, `leadForm`, `submitLead` e `reset`.

La chiave passata a `apiKey` è quella pubblica del widget e non deve avere scope operatore o
canale. In produzione `apiBase` deve usare HTTPS. Chi integra l'SDK deve renderizzare ogni testo
come contenuto, non come HTML, e applicare la propria Content Security Policy.

## Web Component pronto all'uso

```js
import { registerWpAissistantChat } from "@wp-aissistant/browser/widget";
registerWpAissistantChat();
```

```html
<wpai-chat
  api-base="https://backend.wpaissistant.it"
  api-key="CHIAVE_PUBBLICA_WIDGET"
  title="Come possiamo aiutarti?"
  privacy-url="https://example.it/privacy"
></wpai-chat>
```

Il componente usa Shadow DOM, `textContent` per i messaggi, regione `aria-live`, focus gestito e
attributi configurabili. Emette gli eventi DOM `wpai-event` e `wpai-error` per integrazioni custom.
