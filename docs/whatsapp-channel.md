# Canale WhatsApp

Il backend usa un contratto indipendente dal provider. Le credenziali Meta, la versione Graph
API e l'associazione tra tenant e numero restano in un adapter separato; WP AIssistant riceve
e produce soltanto payload normalizzati.

## Inbound

Creare una chiave server-side con scope `channels:write`, quindi inviare a
`POST /channels/whatsapp/inbound`:

```json
{
  "from_number": "+393331234567",
  "from_name": "Mario Rossi",
  "text": "Vorrei assistenza con il mio ordine",
  "message_id": "wamid.001",
  "consent": true,
  "consent_source": "checkbox checkout 2026-08-01"
}
```

`message_id` rende sicuri i retry del webhook. Il numero deve essere E.164. `consent` è
facoltativo: se omesso non modifica lo stato; se vale `true`, `consent_source` è obbligatorio;
se vale `false`, il consenso esistente viene revocato.

## Outbound

`WHATSAPP_OUTBOUND_URL` riceve richieste autenticate con `WHATSAPP_OUTBOUND_TOKEN`.
I messaggi liberi hanno `type: "text"` e vengono inviati solo entro 24 ore dall'ultimo messaggio
del contatto. Fuori finestra il panel disabilita la risposta libera.

I template hanno questo contratto:

```json
{
  "client_id": 4,
  "to": "+393331234567",
  "type": "template",
  "template": "aggiornamento_ordine",
  "language": "it",
  "parameters": ["Mario", "123"]
}
```

Un template viene accettato dal backend soltanto dopo un opt-in esplicito registrato. L'adapter
deve verificare che il template sia approvato per il numero del tenant e restituire un HTTP 2xx
solo dopo l'accettazione da parte del provider.
