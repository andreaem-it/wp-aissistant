# Integrazioni CRM

La prima fondazione CRM collega un tenant a **Brevo**, **Zoho CRM** o **Pipedrive** e permette a un
operatore di inviare esplicitamente un lead dal panel. Lo stato dell'ultimo tentativo resta
visibile sul lead e un nuovo invio aggiorna lo stesso record, senza duplicare la coda locale.

## Confine di sicurezza

Il backend salva soltanto `provider` e `external_account_id`. Token OAuth e API key non entrano
nel database di WP AIssistant: appartengono a un adapter tenant-aware controllato, configurato
con `CRM_ADAPTER_URL` e autenticato tramite `CRM_ADAPTER_TOKEN`.

Il Worker pronto al deploy è in `cloudflare/crm-adapter`. Riceve un `POST /sync` JSON con
`client_id`, `provider`, `external_account_id` e `lead`, e risponde con
`{"ok": true, "external_id": "..."}`. Verifica la tripletta tenant/provider/account prima di
leggere il token del provider. Brevo e Zoho usano l'upsert per email; Pipedrive cerca prima la
persona per email e poi la crea o aggiorna, così un retry non genera doppioni.

## Configurazione Worker

Impostare come secret Cloudflare:

- `ADAPTER_TOKEN`: bearer condiviso soltanto con il backend;
- `CRM_TENANTS_JSON`: configurazione privata degli account, ad esempio
  `{"12":{"brevo":{"account_id":"123","access_token":"..."},"zoho":{"account_id":"acme","access_token":"...","api_domain":"https://www.zohoapis.eu"}}}`.

Nel backend impostare `CRM_ADAPTER_URL=https://<worker>/sync` e `CRM_ADAPTER_TOKEN` con lo
stesso valore di `ADAPTER_TOKEN`. I token dei provider non devono essere copiati nel backend.

## Limiti della fondazione

- La sincronizzazione è manuale e intenzionale: non rallenta la raccolta del lead nel widget.
- Il consenso OAuth self-service deve ancora sostituire l'inserimento amministrativo dei token nel secret del Worker.
- Mapping personalizzato dei campi, aggiornamenti bidirezionali e Salesforce restano fuori MVP.
