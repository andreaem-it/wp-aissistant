# CDN del widget (`wp-aissistant-cdn`)

Bucket R2 pubblico, servito da `cdn.wpaissistant.it`, da cui ogni sito cliente carica il widget.

## Perché serve una regola CORS

Il tag `<script>` del widget porta `integrity` (SRI), e un tag con `integrity` **deve** portare
anche `crossorigin="anonymous"`: quel fetch è in modalità CORS. Senza
`Access-Control-Allow-Origin` sulla risposta il browser **scarta il file che ha appena
scaricato**, e il widget non compare.

È un fallimento che non si vede da fuori: il `put` va a buon fine, l'URL risponde `200`,
l'impronta coincide con l'SRI. Solo un browser lo rifiuta — `curl` non fa CORS. Ci è costato una
mezz'ora sul nostro stesso sito, e nel plugin WordPress si sarebbe manifestato peggio: il ripiego
`onerror` avrebbe caricato la copia dal pacchetto, quindi tutto sembrava funzionare mentre dal
CDN non si prendeva niente.

`origins: ["*"]` è corretto qui: è codice pubblico, che deve caricarsi dal sito di qualunque
cliente. Non c'è niente da proteggere in una lista di domini — l'autorizzazione la fa il backend
sull'`Origin` della chiamata di chat, non il CDN sul download di un file pubblico.

## Il formato del file

L'API R2 vuole un **oggetto con una chiave `rules`**, non un array di regole:
`{"rules": [...]}`. Un array nudo viene rifiutato con un messaggio che rimanda alla
documentazione dell'API, non alla forma attesa.

## Applicare

```sh
npx wrangler r2 bucket cors set wp-aissistant-cdn --file cloudflare/cdn/cors.json
npx wrangler r2 bucket cors list wp-aissistant-cdn   # verifica
```

> `--remote` qui non esiste: serve a `r2 object put`, che senza di esso scriverebbe sul
> simulatore locale, ma la configurazione del bucket è per definizione remota.

Poi la prova che conta, quella che un browser accetterebbe:

```sh
curl -sI -H "Origin: https://esempio.it" \
  https://cdn.wpaissistant.it/widget/0.1.0/wpai-widget.js | grep -i access-control-allow-origin
```

Il workflow `publish-widget.yml` fa lo stesso controllo a ogni pubblicazione e **fallisce** se
l'intestazione manca: questo errore non può ripresentarsi in silenzio.
