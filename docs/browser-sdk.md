# SDK browser headless

`sdk/browser` espone il motore conversazionale senza imporre il widget WordPress. È pensato per
siti custom, shop headless e applicazioni che vogliono disegnare autonomamente l'interfaccia.

## Installazione

```sh
npm install @wp-aissistant/browser
```

Il pacchetto è ESM puro, senza dipendenze e senza step di build: funziona anche via CDN
(`https://esm.sh/@wp-aissistant/browser`). Le dichiarazioni TypeScript sono incluse, non serve
alcun pacchetto `@types/*`.

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

## Pubblicazione su npm

Il pacchetto si chiama `@wp-aissistant/browser` ed è distribuito con licenza MIT
(`sdk/browser/LICENSE`): il codice che gira nel browser del cliente è permissivo, il backend
resta proprietario. Il tarball contiene solo `src/`, `README.md` e `LICENSE` — sette file
verificati da un test, così un file di lavoro non finisce in produzione per errore.

Controlli locali prima di rilasciare:

```sh
cd sdk/browser
npm test          # unit test del client + contratto del pacchetto
npm run types     # compila le dichiarazioni .d.ts con TypeScript in strict mode
npm pack --dry-run
```

Gli stessi tre controlli girano in CI nel job **Headless browser SDK**.

Rilascio:

1. Aggiorna `version` in `sdk/browser/package.json` seguendo semver. Fino alla `1.0.0` una
   modifica incompatibile alza la *minor*.
2. Aggiorna il `README.md` del pacchetto se l'API pubblica è cambiata: è la pagina che npm
   mostra ai clienti.
3. Commit su `main`, poi tag `sdk-v<versione>` (esempio: `sdk-v0.1.1`) e push del tag.
4. Il workflow `publish-sdk.yml` ripete test, typecheck e verifica che il tag corrisponda alla
   versione del pacchetto, poi esegue `npm publish --provenance --access public`.

Prerequisiti una tantum, da fare con l'account npm proprietario dello scope:

- creare l'organizzazione/scope `@wp-aissistant` su npm;
- generare un token di pubblicazione **granulare** limitato a quel pacchetto e salvarlo come
  secret `NPM_TOKEN` del repository;
- la provenance firmata richiede repository pubblico e viene emessa da GitHub Actions con
  `id-token: write`, già configurato nel workflow.

Una versione npm non si sovrascrive: per un errore si pubblica una patch, non si riscrive il
tag. Il workflow accetta anche l'avvio manuale con `dry_run` per provare l'intera catena senza
pubblicare.
