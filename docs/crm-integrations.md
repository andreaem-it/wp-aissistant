# Integrazioni CRM

La prima fondazione CRM collega un tenant a **HubSpot** o **Pipedrive** e permette a un
operatore di inviare esplicitamente un lead dal panel. Lo stato dell'ultimo tentativo resta
visibile sul lead e un nuovo invio aggiorna lo stesso record, senza duplicare la coda locale.

## Confine di sicurezza

Il backend salva soltanto `provider` e `external_account_id`. Token OAuth e API key non entrano
nel database di WP AIssistant: appartengono a un adapter tenant-aware controllato, configurato
con `CRM_ADAPTER_URL` e autenticato tramite `CRM_ADAPTER_TOKEN`.

L'adapter riceve un `POST` JSON con `client_id`, `provider`, `external_account_id` e `lead`, e
risponde con `{"ok": true, "external_id": "..."}`. Deve verificare che la coppia tenant/account
sia autorizzata prima di usare le credenziali del provider.

## Limiti della fondazione

- La sincronizzazione è manuale e intenzionale: non rallenta la raccolta del lead nel widget.
- L'adapter live e il consenso OAuth dei due provider devono ancora essere distribuiti.
- Mapping personalizzato dei campi, aggiornamenti bidirezionali e Salesforce restano fuori MVP.
