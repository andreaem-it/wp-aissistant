# Messenger e Instagram Direct

Il backend espone un contratto normalizzato condiviso dai due canali Meta. Le credenziali
Graph API, la verifica delle firme webhook e la mappatura pagina/account restano in un adapter
tenant-aware esterno al backend.

## Inbound

`POST /channels/meta/inbound`, autenticato con una API key avente scope `channels:write`:

```json
{
  "platform": "messenger",
  "sender_id": "psid_12345",
  "sender_name": "Mario Rossi",
  "text": "Ho bisogno di assistenza",
  "message_id": "mid.001",
  "thread_id": "thread.001"
}
```

`platform` accetta `messenger` o `instagram`. `message_id` rende i retry idempotenti;
`thread_id` mantiene i messaggi nella stessa conversazione. Se manca, viene usato
`sender_id`. Contatti, conversazioni, ticket, routing e SLA restano isolati per tenant.

### Media in arrivo

Foto e file si inviano nello stesso payload, già scaricati dall'adapter con il token Meta:

```json
{
  "platform": "instagram",
  "sender_id": "psid_12345",
  "text": "",
  "message_id": "mid.002",
  "attachments": [
    { "filename": "storia.jpg", "content_type": "image/jpeg", "data": "<base64>" }
  ]
}
```

Il backend non conserva token del provider e non segue URL remoti: riceve solo byte. Limiti
comuni a tutti i canali: massimo 5 file, 10 MB per file e 10 MB complessivi, solo content type
in whitelist (niente SVG), payload malformato rifiutato per intero. Con almeno un allegato
valido `text` può essere vuoto.

## Outbound

Le risposte operatore vengono inviate a `META_MESSAGING_OUTBOUND_URL` con bearer token
`META_MESSAGING_OUTBOUND_TOKEN`. Il payload normalizzato contiene `client_id`, `platform`,
`recipient_id`, `text` e l'eventuale `reply_to_message_id`. Una mancata consegna non viene
presentata come successo: il messaggio resta nello storico e il panel riceve
`delivered: false`.

## Worker Meta

L'adapter è in `cloudflare/meta-messaging-adapter` e serve entrambe le direzioni:

| Rotta | A cosa serve |
|---|---|
| `GET /webhook` | verifica della sottoscrizione (`hub.verify_token` confrontato a tempo costante) |
| `POST /webhook` | eventi Messenger/Instagram, con firma `X-Hub-Signature-256` obbligatoria |
| `POST /send` | risposte operatore, protette da `OUTBOUND_TOKEN` |
| `GET /health` | stato |

Segreti da impostare con `wrangler secret put`: `META_APP_SECRET`, `META_VERIFY_TOKEN`,
`OUTBOUND_TOKEN` e `META_TENANTS_JSON`. Quest'ultimo mappa i tenant e resta fuori dal database
applicativo:

```json
{
  "4": {
    "page_id": "1234",
    "instagram_id": "5678",
    "access_token": "page-access-token",
    "channel_api_key": "chiave-backend-channels-write"
  }
}
```

L'`entry.id` del webhook viene confrontato con `page_id` per Messenger e con `instagram_id` per
Instagram: la pagina di un tenant non può valere come account Instagram di un altro. Se l'id non
è mappato l'evento viene ignorato, non instradato a caso.

Comportamenti che vale la pena conoscere:

- **gli echo vengono scartati.** Meta rimanda indietro i nostri stessi invii con `is_echo`:
  inoltrarli creerebbe messaggi duplicati attribuiti al cliente.
- **consegne, letture e reazioni non diventano messaggi**; un `postback` sì, con un id stabile
  fra i retry anche quando Meta non fornisce un `mid`.
- **gli allegati vengono scaricati dal Worker** e inoltrati come byte. L'URL del CDN è già
  firmato, quindi viene scaricato **senza** token: il segreto del tenant non esce nemmeno per
  errore, e un URL fuori dagli host Meta non viene proprio chiamato. Valgono i limiti del
  backend, con troncamento e nota `[N allegati non inoltrati]` nel corpo.
- **il nome del contatto** viene chiesto a Graph solo se il token della pagina ha i permessi:
  se la chiamata fallisce il messaggio arriva comunque, senza nome.
- **`reply_to` non viene usato** nella Send API: Messenger non lo supporta e un campo rifiutato
  dal provider trasformerebbe una risposta dell'operatore in una mancata consegna.

Prima del rilascio live restano da fare presso Meta: app in modalità live, sottoscrizione degli
eventi `messages` e `messaging_postbacks` per la pagina e per l'account Instagram, permessi
`pages_messaging` / `instagram_manage_messages` e revisione dell'app.
