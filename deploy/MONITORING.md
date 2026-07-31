# Monitoring & alerting

Due livelli, complementari:

1. **Error tracking (Sentry)** — cattura le eccezioni non gestite del backend, con stack
   trace e contesto della richiesta, e ti avvisa quando qualcosa si rompe.
2. **Uptime monitor** — controlla dall'esterno che il servizio risponda, e ti avvisa se è
   giù (cosa che Sentry, da solo, non fa se il processo è morto).

---

## 1. Sentry (error tracking)

L'integrazione è **opt-in**: senza `SENTRY_DSN` è disattivata (no-op). Quando è impostata,
`sentry-sdk` strumenta automaticamente FastAPI e cattura le eccezioni non gestite.

**Setup:**
1. Crea un progetto su [sentry.io](https://sentry.io) (piano free ok), tipo *Python / FastAPI*.
2. Copia il **DSN** del progetto.
3. Su Railway → servizio backend → Variables:
   ```
   SENTRY_DSN=https://…@…ingest.sentry.io/…
   SENTRY_ENV=production
   APP_VERSION=<tag/commit>          # usato come "release" in Sentry
   # SENTRY_TRACES_SAMPLE_RATE=0.1   # opzionale: tracing performance (0 = solo errori)
   ```
4. Salva → al redeploy il backend logga `sentry.enabled`. In Sentry configura gli **Alert**
   (es. email/Slack su nuovo issue o su un picco di errori).

**Privacy:** `send_default_pii=False` — non inviamo messaggi/email dei visitatori a Sentry.
Verifica che le tue integrazioni/alert non aggiungano PII.

**Test rapido:** con il DSN attivo, un endpoint che solleva un'eccezione non gestita deve
comparire come issue in Sentry entro pochi secondi.

---

## 2. Uptime monitor (health check esterno)

Il backend espone `GET /health` (senza auth) che risponde `{"status":"ok"}`. Puntaci un
monitor esterno che ti avvisi quando è giù.

**Opzione consigliata (gratis): UptimeRobot**
1. Account su [uptimerobot.com](https://uptimerobot.com).
2. New Monitor → *HTTP(s)* → URL `https://wp-aissistant-production.up.railway.app/health`.
3. Intervallo 1–5 min. Alert contacts: email/SMS/Slack/Telegram.
4. (Opzionale) *Keyword monitor* sulla stringa `"status":"ok"` per accorgerti anche di un
   200 "vuoto" o di un DB down.

Alternative equivalenti: Better Uptime, Pingdom, Checkly, o gli **Uptime/Cron monitors** di
Sentry stesso.

**Nota Railway:** l'healthcheck del container (in `docker-compose`/Railway) fa ripartire il
processo se non risponde, ma **non ti avvisa**. L'uptime monitor esterno è ciò che ti manda
la notifica.

---

## Cosa già c'è nel prodotto

- **Log JSON strutturati** con `request_id` (stdout → log di Railway).
- **`GET /admin/health`** (superadmin): DB, coda ingest, worker, migrazione, modelli, versione,
  stato email — utile per una diagnosi rapida dal pannello.
- **`/metrics`** Prometheus (token-gated) per dashboard/alert su latenza e conteggi.

Sentry + uptime monitor coprono il buco: **essere avvisati proattivamente** quando qualcosa
va storto in produzione.

## 3. Alert Prometheus pronti

[`prometheus-alerts.yml`](./prometheus-alerts.yml) contiene regole iniziali per:

- backend irraggiungibile;
- percentuale di errori 5xx superiore al 5%;
- latenza p95 di chat/stream superiore a 8 secondi;
- job ingest falliti;
- indisponibilità del provider AI.

Carica il file in Prometheus/Alertmanager oppure traduci le stesse soglie nel servizio di
monitoraggio scelto. Prima del go-live, collegare almeno un destinatario primario e uno di
backup e generare deliberatamente un alert di prova. Un'integrazione configurata ma mai
provata non è considerata operativa.

### Runbook sintetico

1. **Backend down:** controllare deploy Railway, health check e raggiungibilità database.
2. **5xx:** correlare la finestra con Sentry e `request_id` nei log Railway.
3. **Latenza:** separare provider AI, retrieval/DB e saturazione applicativa.
4. **Ingest:** aprire Sistema nel superadmin, controllare errori e retry prima di rilanciare.
5. **LLM down:** verificare Cloudflare Workers AI e credenziali; informare gli operatori del
   fallback a ticket finché il provider non recupera.
