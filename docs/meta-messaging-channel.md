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
valido `text` può essere vuoto. Il Worker Meta deve scaricare il media e inoltrarlo qui.

## Outbound

Le risposte operatore vengono inviate a `META_MESSAGING_OUTBOUND_URL` con bearer token
`META_MESSAGING_OUTBOUND_TOKEN`. Il payload normalizzato contiene `client_id`, `platform`,
`recipient_id`, `text` e l'eventuale `reply_to_message_id`. Una mancata consegna non viene
presentata come successo: il messaggio resta nello storico e il panel riceve
`delivered: false`.

## Attivazione provider

Prima del rilascio live servono un adapter Meta con verifica firma, sottoscrizione degli eventi
Messenger/Instagram, mapping sicuro pagina/account → tenant e credenziali conservate fuori dal
database applicativo.
