# @wp-aissistant/widget

Il widget di chat di **WP AIssistant**: un bundle senza dipendenze, configurato con coppie
proprietà/valore, che gira su qualunque sito — non solo WordPress.

È lo stesso artefatto che carica il plugin WordPress. Un widget solo, non due che divergono alla
prima correzione fatta da una parte sola.

## Uso

```html
<link rel="stylesheet" href="https://cdn.wpaissistant.it/widget/v1/wpai-widget.css">
<script>
  window.WPAissistantConfig = {
    apiKey: "CHIAVE_PUBBLICA",
    site: "https://esempio.it",
    appearance: { theme: "light", position: "right", color: "#635bff" },
    texts: { title: "Come possiamo aiutarti?" }
  };
</script>
<script async src="https://cdn.wpaissistant.it/widget/v1/wpai-widget.js"></script>
```

**Non c'è un `backendUrl`**: l'indirizzo del backend è compilato nell'artefatto
(`src/backend.js`). Come opzione sarebbe stato un indirizzo congelato nelle pagine di ogni
cliente, e per cambiarlo avremmo dovuto chiederlo a tutti. Si sostituisce in fase di build
(`WPAI_BACKEND_URL=… npm run build`), che è come lo cambiamo noi per lo sviluppo; nel bundle
pubblicato un `backendUrl` nella configurazione viene ignorato.

`site` è **obbligatorio**: la licenza è legata al dominio e il backend rifiuta una chiamata da un
sito non registrato. Dichiararlo serve a fallire subito e in chiaro — un messaggio in console per
chi installa — invece di un `403` remoto che al visitatore appare come un widget che non c'è. Non
è quel valore ad autorizzare: l'autorizzazione la fa il backend sull'header `Origin`, che la
pagina non può falsificare.

Serve anche il CSS: `wpai-widget.css`, accanto al bundle.

Il bundle **non chiede niente a nessun altro dominio**: le icone sono SVG al suo interno, non un
font di terze parti. Lo erano, e il difetto si vedeva solo dove la dipendenza mancava — cioè in
ogni installazione che non fosse il plugin WordPress, che la forniva per conto suo.

La guida per chi integra è [`docs/embedded-widget.md`](../../docs/embedded-widget.md).

## Opzioni

I valori ammessi stanno in [`src/schema.js`](src/schema.js), **una volta sola**: un valore fuori
vocabolario ricade sul default invece di finire nel DOM. Aspetto (`appearance`): `theme`,
`position`, `motion`, `launcherStyle`, `launcherIcon`, `launcherSize`, `windowStyle`,
`windowSize`, `headerStyle`, `cornerStyle`, `fontSize`, `showAvatar`, `showStatus`, `color`.
Testi: `title`, `subtitle`, `welcome`, `aiDisclosure`, `launcherLabel`, `inputPlaceholder`,
`privacyUrl`, `image`.

## L'adapter della piattaforma ospite

`config.host` è **opzionale**: senza, il widget funziona — niente carrello e niente dati completi
dell'ordine, che è il comportamento giusto su un sito che non vende da sé.

| Capacità | A cosa serve |
|---|---|
| `siteUrl` | la callback della ricerca ordini. L'header `Origin` non porta il percorso, quindi un'installazione in sottocartella costruirebbe una URL sbagliata |
| `identityToken()` | prova d'identità del visitatore: il backend dà i dati completi dell'ordine invece del solo stato |
| `addToCart(product, button)` | aggiunta al carrello e ciò che ne segue sulla piattaforma. Restituisce `{ optionsUrl }` se il prodotto ha varianti da scegliere |
| `cartItemCount()` | quante cose ci sono nel carrello, per le regole proattive che dipendono da questo |
| `chatHeaders()` | header in più sulle sole chiamate di chat. Lo usa il pannello per il token di contesto del tenant loggato |

L'adapter WordPress è in `wp-plugin/wp-aissistant/assets/wp-host.js`.

## Distribuzione

Due canali, due compromessi opposti, e la scelta si fa una volta per canale:

```
https://cdn.wpaissistant.it/widget/v1/wpai-widget.js       stabile — lo snippet dei clienti
https://cdn.wpaissistant.it/widget/0.2.0/wpai-widget.js    immutabile, con SRI — il plugin
```

**Il percorso stabile è il default per l'integrazione JavaScript.** Uno snippet incollato nel
sito di un cliente non si può riscrivere: con la versione dentro l'URL, correggere un difetto
significherebbe chiedere a ognuno di ricopiare, cioè non poterlo fare. Il costo è dichiarato —
su un percorso che cambia non si può mettere `integrity`, perché un'impronta fissa e un file che
si aggiorna sono la stessa cosa detta in due modi opposti.

**Il plugin invece pinna una versione con SRI**, e può permetterselo: ha il bundle nel pacchetto
come ripiego e un canale di aggiornamento suo (`GET /plugin/update`). Lì la versione fissa non
congela niente che non si muova comunque.

Il bordo serve `v1` per **quattro ore**: una correzione impiega fino a quel tempo ad arrivare
ovunque.

**Il bucket ha bisogno di una regola CORS.** Un tag con `integrity` porta anche
`crossorigin="anonymous"`, e quel fetch è in modalità CORS: senza `Access-Control-Allow-Origin`
il browser scarta il file che ha appena scaricato. La regola è versionata in
[`cloudflare/cdn/cors.json`](../../cloudflare/cdn/README.md), e il workflow di pubblicazione
fallisce se manca **prima** di pubblicare — applicarla dopo non corregge una risposta già
salvata al bordo con un anno di cache.

**Prima il widget, poi il plugin.** Il plugin punta a una versione fissa: se non è ancora sul
CDN, ogni sito cade sul ripiego locale in silenzio. `wp-plugin/build.sh` avvisa, e il workflow
del plugin fallisce.

La pubblicazione avviene su tag `widget-v*` (`.github/workflows/publish-widget.yml`), dopo i
test, e verifica che il file sia **davvero raggiungibile da un browser**, che corrisponda
all'SRI e che l'alias serva questa versione: un `put` riuscito non dimostra niente di tutto ciò.

## Sviluppo

```sh
npm install
npm test     # i18n, regole, vocabolario e montaggio in jsdom
npm run build # dist/wpai-widget.js + .css
```

`mount()` restituisce un oggetto con `destroy()`, che rimuove il DOM **e ferma il polling**:
dentro un'applicazione a pagina singola, senza, resterebbe un poller per ogni visita.
