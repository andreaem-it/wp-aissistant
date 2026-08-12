# @wp-aissistant/widget

Il widget di chat di **WP AIssistant**: un bundle senza dipendenze, configurato con coppie
proprietà/valore, che gira su qualunque sito — non solo WordPress.

È lo stesso artefatto che carica il plugin WordPress. Un widget solo, non due che divergono alla
prima correzione fatta da una parte sola.

## Uso

```html
<script>
  window.WPAissistantConfig = {
    apiKey: "CHIAVE_PUBBLICA",
    backendUrl: "https://backend.wpaissistant.it",
    site: "https://esempio.it",
    appearance: { theme: "light", position: "right", color: "#635bff" },
    texts: { title: "Come possiamo aiutarti?" }
  };
</script>
<script async src="/wpai-widget.js"></script>
```

`site` è **obbligatorio**: la licenza è legata al dominio e il backend rifiuta una chiamata da un
sito non registrato. Dichiararlo serve a fallire subito e in chiaro — un messaggio in console per
chi installa — invece di un `403` remoto che al visitatore appare come un widget che non c'è. Non
è quel valore ad autorizzare: l'autorizzazione la fa il backend sull'header `Origin`, che la
pagina non può falsificare.

Serve anche il CSS: `wpai-widget.css`, accanto al bundle.

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

L'adapter WordPress è in `wp-plugin/wp-aissistant/assets/wp-host.js`.

## Sviluppo

```sh
npm install
npm test     # i18n, regole, vocabolario e montaggio in jsdom
npm run build # dist/wpai-widget.js + .css
```

`mount()` restituisce un oggetto con `destroy()`, che rimuove il DOM **e ferma il polling**:
dentro un'applicazione a pagina singola, senza, resterebbe un poller per ogni visita.
