# Integrazioni helpdesk

WP AIssistant può trasferire un ticket a **Zendesk** o **Freshdesk** mantenendo contatto,
canale, priorità e cronologia completa della conversazione. L’operatore configura la destinazione
nel pannello Ticket e avvia l’handoff con un pulsante sul singolo ticket.

## Sicurezza e responsabilità

Il backend non conserva token o password dei provider. Invia un payload normalizzato a un adapter
HTTPS fidato e tenant-aware, autenticato con un Bearer token condiviso. L’adapter custodisce le
credenziali dei provider e traduce il payload nelle rispettive API.

Variabili backend:

- `HELPDESK_ADAPTER_URL`: endpoint POST dell’adapter.
- `HELPDESK_ADAPTER_TOKEN`: segreto backend→adapter.
- `HELPDESK_ADAPTER_TIMEOUT`: timeout in secondi, predefinito `10`.

Ogni handoff è idempotente per coppia connessione/ticket. Un nuovo tentativo aggiorna lo stesso
record, mostrando nel panel `pending`, `delivered` o `failed`, l’ID esterno e l’eventuale URL.

## Contratto adapter

La richiesta contiene `client_id`, `provider`, `external_account_id` e `ticket`. Il ticket include
motivo, stato, conversazione, contatto e messaggi ordinati. Una risposta positiva usa:

```json
{"ok": true, "external_id": "123", "external_url": "https://helpdesk.example/tickets/123"}
```

La configurazione iniziale registra soltanto l’account di destinazione. Prima dell’uso live devono
essere configurate nell’adapter le credenziali Zendesk/Freshdesk del tenant corrispondente.
