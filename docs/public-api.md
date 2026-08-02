# API pubblica e webhook

Interfaccia per collegare WP AIssistant a CRM, automation platform e sistemi propri.
Due meccanismi complementari:

- **API `/v1`** — tu chiami noi: leggi e aggiorni conversazioni, aggiungi contenuti, leggi le
  statistiche.
- **Webhook** — noi chiamiamo te: ricevi gli eventi quando succedono, firmati e con retry.

Entrambi si configurano dal panel, sezione **API e webhook**.

## Autenticazione

Le chiamate `/v1` usano una **chiave API** con permessi limitati, diversa dalla `api_key` del
widget (quella è pubblica per costruzione e identifica solo il tenant, non autorizza nulla di
tutto questo).

```http
Authorization: Bearer wpa_<prefisso>_<segreto>
```

La chiave in chiaro è mostrata **una sola volta** alla creazione: nel database resta solo il
digest SHA-256. Se la perdi, revocala e creane un'altra. Una chiave revocata smette di
funzionare immediatamente (`401`).

### Permessi (scope)

| Scope | Cosa autorizza |
|---|---|
| `conversations:read` | Elenco e dettaglio delle conversazioni |
| `conversations:write` | Rispondere, cambiare stato, applicare tag |
| `knowledge:write` | Aggiungere documenti alla knowledge base |
| `stats:read` | Leggere le statistiche |

Una chiamata senza lo scope necessario risponde `403` con il permesso richiesto nel messaggio.
Ogni chiave ha un rate limit dedicato (`PUBLIC_API_RATE_LIMIT`, default 120 richieste/minuto).

## Endpoint

Tutte le risposte sono JSON. Gli id delle risorse sono validi solo dentro il proprio tenant:
una risorsa di un altro tenant risponde `404`, mai `403`, per non rivelarne l'esistenza.

### `GET /v1/conversations`

Parametri: `status` (`open|escalated|closed`), `priority` (`low|normal|high|urgent`), `tag_id`,
`limit` (default 50, max 200), `before_id` per la paginazione.

```json
{
  "data": [
    {
      "id": 128,
      "visitor_id": "e0b1…",
      "status": "escalated",
      "priority": "high",
      "department_id": 3,
      "assigned_operator_id": 7,
      "created_at": "2026-08-01T09:12:04Z",
      "updated_at": "2026-08-01T09:15:31Z",
      "closed_at": null,
      "tags": ["Resi"],
      "classification": {"intent": "reso", "topic": "reso scarpe", "urgency": "alta", "classified_at": "…"},
      "sla": {"state": "in_scadenza", "first_response": {"due_at": "…", "met_at": null, "state": "in_scadenza"}},
      "rating": null
    }
  ],
  "next_before_id": 128
}
```

Per la pagina successiva richiama con `before_id=<next_before_id>`.

### `GET /v1/conversations/{id}`

Come sopra, più `messages` (`user | assistant | operator`). Le **note interne non sono mai
incluse**: restano visibili solo agli operatori nel panel.

### `POST /v1/conversations/{id}/reply`

```json
{ "reply": "Le abbiamo spedito l'etichetta di reso." }
```

Si comporta come una risposta dell'operatore: riapre la conversazione, chiude i ticket aperti,
ferma la scadenza SLA di prima risposta e notifica il visitatore via email se l'ha lasciata.

### `POST /v1/conversations/{id}/status`

```json
{ "status": "closed" }
```

`open` o `closed`. La chiusura ferma la scadenza SLA di risoluzione ed emette
`conversation.closed`.

### `POST /v1/conversations/{id}/tags`

```json
{ "name": "Da fatturare" }
```

Applica il tag, creandolo se non esiste (confronto senza distinzione di maiuscole).

### `GET /v1/stats`

Gli stessi aggregati della pagina Statistiche: conversazioni, risoluzione AI, feedback, SLA,
tag, classificazione e CSAT.

### `POST /v1/knowledge/documents`

```json
{ "title": "Politica resi 2026", "text": "…" }
```

Accoda il documento (chunking ed embedding avvengono in background) e risponde con
`{"job_id": 42, "status": "queued"}`. Lo stato si controlla su `GET /ingest/jobs/{id}` con la
stessa chiave.

## Webhook

Un endpoint riceve gli eventi selezionati; senza selezione li riceve tutti.

| Evento | Quando |
|---|---|
| `conversation.created` | Il visitatore apre una conversazione |
| `conversation.message.received` | Arriva un messaggio su web, email, WhatsApp, Messenger o Instagram; contiene solo ID conversazione/messaggio, canale e ruolo |
| `conversation.escalated` | La conversazione passa a un operatore (creato il ticket) |
| `conversation.replied` | Un operatore o l'API risponde |
| `conversation.closed` | La conversazione viene chiusa |
| `conversation.rated` | Il visitatore lascia il voto CSAT |
| `sla.breached` | Una scadenza SLA viene superata |
| `lead.captured` | Un visitatore compila il form di qualificazione (payload con punteggio e campi) |

Corpo della richiesta (`POST`, `application/json`):

```json
{
  "event": "conversation.escalated",
  "created_at": "2026-08-01T09:15:31Z",
  "data": { "conversation_id": 128, "ticket_id": 44, "reason": "rimborso", "trigger": "keyword" }
}
```

Header inviati: `X-WPAI-Event`, `X-WPAI-Delivery` (id della consegna, utile per l'idempotenza)
e `X-WPAI-Signature`.

### Verificare la firma

`X-WPAI-Signature: t=<unix>,v1=<hex>` dove l'HMAC-SHA256 è calcolato su `"<t>." + corpo grezzo`
con il segreto dell'endpoint (mostrato una sola volta alla creazione).

```python
import hashlib, hmac, time

def verifica(corpo: bytes, header: str, segreto: str, tolleranza: int = 300) -> bool:
    parti = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parti["t"])) > tolleranza:
        return False  # troppo vecchia: possibile replay
    atteso = hmac.new(segreto.encode(), f'{parti["t"]}.'.encode() + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(atteso, parti["v1"])
```

Confronta sempre in tempo costante (`hmac.compare_digest`) e usa il **corpo grezzo**, non il
JSON ri-serializzato.

### Consegna e riprovi

Una consegna è riuscita con risposta `2xx`. Altrimenti viene ritentata con backoff esponenziale
(30s, 1m, 2m, 4m… fino a un'ora) per un massimo di 5 tentativi, poi resta registrata come
`failed`. Lo storico è consultabile dal panel per ogni endpoint, con stato, tentativi, codice
HTTP ed errore.

L'endpoint dovrebbe rispondere **subito** (entro 5 secondi) e fare il lavoro pesante in
asincrono. Poiché un tentativo può essere consegnato più di una volta, tratta
`X-WPAI-Delivery` come chiave di idempotenza.

### Sicurezza degli URL

La destinazione è scelta dal tenant, quindi è un potenziale vettore SSRF: sono ammessi solo URL
`https://` pubblici. Indirizzi loopback, privati, link-local e riservati vengono rifiutati alla
creazione e ricontrollati (risolvendo il nome) prima di ogni consegna. In sviluppo si può
allentare il vincolo con `WEBHOOK_ALLOW_PRIVATE=true`.

## Errori

| Codice | Significato |
|---|---|
| `400` | Parametri non validi |
| `401` | Chiave assente, sconosciuta o revocata |
| `403` | Chiave valida ma senza lo scope richiesto |
| `404` | Risorsa inesistente o di un altro tenant |
| `413` | Contenuto troppo grande |
| `429` | Rate limit della chiave superato |
| `503` | Funzione temporaneamente non disponibile (es. classificazione AI) |
