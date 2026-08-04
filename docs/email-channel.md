# Canale email

Il backend espone un adapter normalizzato e indipendente dal provider:

```http
POST /channels/email/inbound
Authorization: Bearer <scoped_api_key>
Content-Type: application/json

{
  "from_email": "cliente@example.com",
  "from_name": "Mario Rossi",
  "subject": "Problema con un ordine",
  "text": "Non riesco a trovare il mio ordine.",
  "message_id": "<messaggio-univoco@example.com>",
  "thread_id": "<thread-stabile@example.com>",
  "in_reply_to": ""
}
```

Il webhook inbound del provider va trasformato in questo formato da un adapter sottile (Worker,
Function o route applicativa). `message_id` è obbligatorio e rende sicuri i retry del provider;
`thread_id` deve restare stabile per tutta la catena. Se il provider non lo espone, usare il
Message-ID iniziale e inviare sulle risposte il valore di `In-Reply-To`.

### Allegati

L'adapter può inoltrare gli allegati già decodificati, nello stesso payload:

```json
{
  "from_email": "cliente@example.com",
  "subject": "Foto del prodotto difettoso",
  "text": "",
  "message_id": "<con-foto@example.com>",
  "attachments": [
    { "filename": "difetto.jpg", "content_type": "image/jpeg", "data": "<base64>" }
  ]
}
```

Valgono i limiti comuni a tutti i canali: massimo 5 file, 10 MB per file e 10 MB complessivi,
solo i content type in whitelist (niente SVG), payload rifiutato per intero se malformato
(400/413/415). Con almeno un allegato valido `text` può essere vuoto. I byte finiscono nello
storage privato R2 e restano scaricabili solo con una sessione operatore; se lo storage non
risponde il messaggio non va perso e nel thread compare `[N allegati non salvati]`.

Il Worker `cloudflare/email-router` incluso nel repo estrae gli allegati MIME e li inoltra già
in questo formato. Regole dell'adapter, pensate per non far mai rifiutare l'intera email:

- tronca ai limiti del backend (5 file, 10 MB per file e complessivi) invece di inoltrare tutto
  e farsi rifiutare il messaggio; quello che resta fuori viene dichiarato nel corpo come
  `[N allegati non inoltrati]`, così l'operatore sa di dover chiedere di nuovo il file;
- scarta in silenzio gli allegati `inline` sotto 8 KB: sono loghi di firma e pixel di
  tracciamento, non contenuto del cliente. Una schermata incollata nel corpo passa;
- un'email con soli allegati non viene più rifiutata: viene rifiutata solo quando non c'è
  né testo né un allegato utilizzabile.

Una nuova email crea una conversazione con canale `email`, un contatto tenant-scoped e un ticket
con SLA. Le email successive dello stesso thread vengono aggiunte alla conversazione senza
duplicare ticket ancora aperti. Una risposta dell'operatore dal panel viene inviata al mittente
come corpo dell'email, con oggetto `Re:` e header `In-Reply-To`/`References`.

L'invio usa la configurazione transazionale già esistente (`EMAIL_PROVIDER=smtp` oppure
`brevo_api`). In produzione il provider deve essere configurato: in sviluppo, se assente, le email
vengono solo registrate nei log.

Creare dal panel una chiave API dedicata con il solo scope `channels:write`. La `api_key` del
widget è pubblica e viene rifiutata da questo endpoint. La chiave scoped non va inserita in regole
client-side né inoltrata dal provider come parametro URL: conservarla come secret dell'adapter e
inviarla esclusivamente nell'header Authorization.

## Cloudflare Email Routing

L'adapter pronto al deploy è in `cloudflare/email-router`. Usa `postal-mime`, rifiuta email senza
Message-ID o corpo testuale, limita il payload a 10 MB e ignora autoresponder, messaggi bulk e
loop dal proprio indirizzo. Il token `channels:write` va salvato come secret `CHANNEL_API_KEY`.

Dopo il deploy, in Cloudflare Email Routing creare la regola
`support@wpaissistant.it` → Worker `wp-aissistant-email-router`. Il Worker inoltra al backend solo
il contenuto normalizzato; la chiave non transita nell'URL e non è contenuta nel repository.
