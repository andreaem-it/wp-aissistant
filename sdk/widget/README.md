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

## Distribuzione

Il bundle si pubblica su R2 con percorsi **versionati e immutabili**:

```
https://cdn.wpaissistant.it/widget/0.1.0/wpai-widget.js   Cache-Control: immutable, con SRI
https://cdn.wpaissistant.it/widget/v1/wpai-widget.js      alias mobile, cache breve, senza SRI
```

**Prima il widget, poi il plugin.** Il plugin punta a una versione fissa: se non è ancora sul
CDN, ogni sito cade sul ripiego locale in silenzio. `wp-plugin/build.sh` avvisa quando la
versione che sta impacchettando non risponde.

**La versione fissa è il default, non l'opzione avanzata.** Da quando ogni sito cliente carica
il nostro script, un rilascio sbagliato sull'alias mobile non rompe un sito: li rompe tutti
insieme, e non c'è niente che il cliente possa fare. Con la versione fissa il guasto resta
per-sito e si annulla disinstallando. L'alias mobile è una scelta esplicita per chi vuole gli
aggiornamenti automatici, e rinuncia all'SRI — nessuna impronta può descrivere un file che
cambia.

La pubblicazione avviene su tag `widget-v*` (`.github/workflows/publish-widget.yml`), dopo i
test, e verifica che il file sia **davvero raggiungibile da un browser** e corrisponda all'SRI:
un `put` riuscito non dimostra che il dominio del bucket sia collegato.

## Sviluppo

```sh
npm install
npm test     # i18n, regole, vocabolario e montaggio in jsdom
npm run build # dist/wpai-widget.js + .css
```

`mount()` restituisce un oggetto con `destroy()`, che rimuove il DOM **e ferma il polling**:
dentro un'applicazione a pagina singola, senza, resterebbe un poller per ogni visita.
