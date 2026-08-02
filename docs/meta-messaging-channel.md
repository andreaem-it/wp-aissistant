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
