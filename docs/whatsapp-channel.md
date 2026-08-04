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

### Media in arrivo

Foto, PDF, audio e video si inviano nello stesso messaggio, già scaricati dall'adapter:

```json
{
  "from_number": "+393331234567",
  "text": "",
  "message_id": "wamid.002",
  "attachments": [
    { "filename": "foto.jpg", "content_type": "image/jpeg", "data": "<base64>" }
  ]
}
```

È l'adapter a risolvere il `media id` con il token Meta e a scaricare i byte: il backend non
conserva token del provider e non segue mai un URL remoto, quindi sul percorso inbound non
esiste superficie SSRF. Regole applicate:

- `content_type` deve essere fra quelli ammessi (`image/jpeg`, `image/png`, `image/webp`,
  `application/pdf`, `text/plain`, `audio/mpeg`, `audio/ogg`, `video/mp4`): niente SVG.
- massimo 5 allegati per messaggio, 10 MB per file e 10 MB complessivi
  (`ATTACHMENT_MAX_INBOUND_FILES`, `ATTACHMENT_MAX_BYTES`, `ATTACHMENT_MAX_INBOUND_TOTAL_BYTES`).
- un payload malformato viene rifiutato **per intero** (400/413/415): meglio un retry
  dell'adapter che un messaggio salvato a metà.
- con allegati validi `text` può essere vuoto: un messaggio con la sola foto è legittimo.

I byte finiscono nello storage privato R2 e sono scaricabili solo con una sessione operatore.
Se lo storage non risponde il messaggio del cliente **non** viene perso: resta il testo e nel
thread compare `[1 allegato non salvato]`.

Il Worker `cloudflare/whatsapp-adapter` fa già questo lavoro: risolve il `media id` con il token
del tenant, verifica tipo e dimensione dai metadati Graph e scarica i byte. Il token viene
inviato solo a `graph.facebook.com` e agli host CDN di Meta — un URL di download che puntasse
altrove viene scartato senza essere nemmeno chiamato, così il segreto non finisce a un terzo.
Se il download non riesce il messaggio arriva lo stesso con l'etichetta descrittiva
(`[Immagine allegata: …]`): l'operatore vede che il cliente ha inviato qualcosa e può
richiederlo. Quando invece il file è allegato, come testo resta la sola didascalia.

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

## Adapter Meta su Cloudflare

Il Worker pronto per il deploy è in `cloudflare/whatsapp-adapter`. Prima dell'attivazione:

1. impostare in `wrangler.jsonc` una versione Graph API attualmente supportata al posto di
   `vXX.X`;
2. creare i secret `META_VERIFY_TOKEN`, `META_APP_SECRET`, `OUTBOUND_TOKEN` e
   `META_TENANTS_JSON` con `wrangler secret put`;
3. configurare nel backend `WHATSAPP_OUTBOUND_URL=https://<worker>/send` e lo stesso valore
   di `OUTBOUND_TOKEN` in `WHATSAPP_OUTBOUND_TOKEN`;
4. registrare `https://<worker>/webhook` come callback WhatsApp in Meta e sottoscrivere il
   campo `messages`.

`META_TENANTS_JSON` non va mai salvato in un file. La forma del secret è:

```json
{
  "4": {
    "phone_number_id": "ID_NUMERO_META",
    "access_token": "TOKEN_META",
    "channel_api_key": "CHIAVE_WPAI_CHANNELS_WRITE"
  }
}
```

Il Worker verifica `X-Hub-Signature-256` usando `META_APP_SECRET`, associa il numero Meta al
tenant e inoltra al backend solo il payload normalizzato. Eventuali retry Meta restano sicuri
grazie alla deduplicazione su `wamid`.
