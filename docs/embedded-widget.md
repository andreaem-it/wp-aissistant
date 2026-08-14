# Il widget incorporato

Come si mette l'assistente su un sito che non è WordPress — e come si comporta una volta che c'è.

Su WordPress non serve niente di tutto questo: il plugin produce le opzioni e carica lo stesso
artefatto. Questa guida è per l'integrazione JavaScript, che è la strada per chiunque altro.

## Lo snippet

```html
<link rel="stylesheet" href="https://cdn.wpaissistant.it/widget/v1/wpai-widget.css">
<script>
  window.WPAissistantConfig = {
    apiKey: "LA_TUA_CHIAVE_PUBBLICA",
    site: "https://esempio.it",
  };
</script>
<script async src="https://cdn.wpaissistant.it/widget/v1/wpai-widget.js"></script>
```

Va prima di `</body>`. Il pannello lo genera già configurato in *Impostazioni → Installazione*,
con le sole opzioni che hai cambiato rispetto ai default — copiarlo da lì è meglio che scriverlo,
perché uno snippet con ventiquattro valori identici ai default nasconde i due che contano.

**`apiKey` è pubblica per costruzione.** Sta in ogni pagina del tuo sito e chiunque può leggerla:
identifica chi risponde, non autorizza niente. Ciò che la protegge è la licenza legata al
dominio, non la segretezza.

**`site` è obbligatorio.** La licenza è legata al dominio e il backend rifiuta una chiamata da un
sito non registrato. Dichiararlo qui serve a fallire **subito e in chiaro** — un messaggio in
console per chi installa — invece di un `403` remoto che al visitatore appare come una chat che
non c'è. Non è quel valore ad autorizzare: l'autorizzazione la fa il backend sull'header `Origin`,
che la pagina non può falsificare. Registra il dominio in *Impostazioni → Siti e licenza* prima
di installare, altrimenti il widget non parte da nessuna parte.

**Non c'è un `backendUrl`.** L'indirizzo del backend è compilato dentro l'artefatto. Come opzione
sarebbe stato un indirizzo congelato nelle pagine di ogni cliente: per spostare il backend
avremmo dovuto chiedere a tutti di ricopiare lo snippet, cioè non avremmo potuto farlo. Se trovi
uno snippet vecchio che lo contiene, il valore viene semplicemente ignorato.

## Aggiornamenti: perché il percorso non porta la versione

Lo script sta su `/widget/v1/`, un percorso **stabile**. Pubblichiamo lì, e ogni sito prende la
versione nuova senza toccare niente.

È una scelta con un costo dichiarato: **su un percorso che cambia non si può mettere
`integrity`.** Un'impronta fissa e un file che si aggiorna sono la stessa cosa detta in due modi
opposti, e qualunque soluzione che sembra ottenere entrambe sta spostando il problema altrove.
Fra «il cliente verifica il byte» e «possiamo correggere un difetto sul sito del cliente senza
chiederglielo», per un servizio ospitato vince la seconda — ed è il motivo per cui il CDN esiste.

Chi preferisce l'altro compromesso può pinnare una versione immutabile e aggiungere `integrity`
(le impronte stanno in `dist/integrity.json` di ogni release); da quel momento gli aggiornamenti
sono una sua decisione, comprese le correzioni. Il plugin WordPress fa così, ma può permetterselo
perché ha una copia locale di ripiego e un canale di aggiornamento suo.

Una correzione impiega **fino a quattro ore** ad arrivare ovunque: è la cache al bordo del CDN.

## Le opzioni

Il vocabolario è dichiarato **una volta sola**, in
[`sdk/widget/src/schema.js`](../sdk/widget/src/schema.js), e generato in `schema.json` per il
backend e il pannello. Non lo ricopio qui: una lista in prosa diventa la copia che diverge per
prima, e il modo giusto di vederla è il configuratore, che la costruisce da quel file.

In sintesi, per orientarsi:

- **`appearance`** — `theme`, `position`, `motion`, `launcherStyle`, `launcherIcon`,
  `launcherSize`, `windowStyle`, `windowSize`, `headerStyle`, `cornerStyle`, `fontSize`, più i
  booleani `showAvatar` e `showStatus` e il colore `color`.
- **`texts`** — `title`, `subtitle`, `welcome`, `aiDisclosure`, `launcherLabel`,
  `inputPlaceholder`, e i due indirizzi `image` (avatar) e `privacyUrl`.

Un valore fuori vocabolario **non finisce nel DOM**: il widget ricade sul default, perché deve
funzionare comunque. Il configuratore invece lo rifiuta dicendo perché — lì un valore sbagliato è
una cosa da correggere, non da sopravvivere.

I testi si accettano sia annidati sotto `texts` (la forma che genera il pannello) sia in cima
alla configurazione (la forma che usa il plugin). Le due forme sono convissute per un periodo
senza che il widget leggesse la prima: chi scriveva il nome dal configuratore vedeva il default,
e nulla lo diceva. Ora vince quella in cima, se c'è.

**Senza `image` l'avatar è l'iniziale del nome.** Non mettiamo un volto predefinito: suggerirebbe
una persona, e l'assistente dichiara in ogni conversazione di non esserlo.

## L'adapter della piattaforma ospite

`config.host` è **opzionale**. Senza, il widget funziona: niente carrello e niente dati completi
dell'ordine, che è il comportamento giusto su un sito che non vende da sé.

| Capacità | A cosa serve |
|---|---|
| `siteUrl` | la callback della ricerca ordini. L'header `Origin` non porta il percorso, quindi un'installazione in sottocartella costruirebbe una URL sbagliata |
| `identityToken()` | prova d'identità del visitatore: il backend dà i dati completi dell'ordine invece del solo stato |
| `addToCart(product, button)` | aggiunta al carrello e ciò che ne segue. Restituisce `{ optionsUrl }` se il prodotto ha varianti da scegliere |
| `cartItemCount()` | quante cose ci sono nel carrello, per le regole proattive che dipendono da questo |
| `chatHeaders()` | header in più sulle sole chiamate di chat. Lo usa il nostro pannello per il token di contesto del tenant loggato |

`identityToken()` viene chiesto **una volta per pagina**; `chatHeaders()` **a ogni messaggio**,
perché ciò che porta può scadere prima della fine di una conversazione. Un adapter che solleva
non blocca la chat: si prosegue senza quella capacità.

L'adapter WordPress, come esempio completo, è in
[`wp-plugin/wp-aissistant/assets/wp-host.js`](../wp-plugin/wp-aissistant/assets/wp-host.js).

## Controllo da JavaScript

```js
// Se la configurazione arriva dopo il caricamento dello script:
window.WPAissistant.init({ apiKey: "…", site: "https://esempio.it" });
```

`init()` monta una volta sola: due `<script>` nella stessa pagina non producono due widget. Da un
bundler si può importare `mount()` da `@wp-aissistant/widget/widget`, che restituisce un oggetto
con `destroy()` — rimuove il DOM **e ferma il polling**. Dentro un'applicazione a pagina singola,
senza, resterebbe un poller per ogni visita.

**Non c'è (ancora) un'API di eventi.** Il widget non emette `CustomEvent` propri: il punto di
estensione è l'adapter `host`. L'unico evento in giro è `wpai_cart_updated`, che emette l'adapter
WordPress dopo un'aggiunta al carrello — quindi esiste solo lì, e non è un contratto del widget.
Se ti serve agganciarti a qualcosa, chiedi: è più facile aggiungere una capacità all'adapter che
scoprire fra sei mesi che qualcuno dipende da un dettaglio interno.

## Cosa serve sapere prima di installare

- **Il dominio va registrato**, altrimenti `403` e nessun widget. Vale anche per lo staging, che
  ha uno slot suo.
- **`www.esempio.it` e `esempio.it` sono lo stesso sito**, sia per la licenza sia per la CORS:
  registrarne uno basta.
- **Una CSP stretta va aperta** su `cdn.wpaissistant.it` (`script-src`, `style-src`) e su
  `backend.wpaissistant.it` (`connect-src`). Il widget non carica font né immagini da terzi: le
  icone sono SVG dentro il bundle, proprio per non chiedere niente a nessun altro dominio.
- **Il widget non legge cookie e non ne scrive.** Usa `localStorage` per l'identificativo del
  visitatore, la conversazione in corso e lo stato aperto/chiuso.

## Se non compare

In ordine di quanto spesso è la causa:

1. **Guarda la console.** I problemi di installazione finiscono lì in chiaro — dominio non
   registrato, `apiKey` mancante, `site` mancante — e non in chat, perché il visitatore non può
   farci niente.
2. **Controlla il dominio registrato**, incluso lo schema: `https://esempio.it`, non
   `esempio.it`.
3. **Controlla che il CSS sia caricato.** Senza `wpai-widget.css` il widget è nel DOM ma
   invisibile, che sembra identico a «non è partito».
4. **Se hai pinnato una versione con `integrity`**, un'impronta che non corrisponde fa scartare
   lo script al browser *dopo* averlo scaricato: nella scheda rete sembra tutto a posto e in
   console c'è un errore di integrità. È il motivo per cui il percorso stabile non ne usa.
