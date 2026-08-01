# Checklist P0 di produzione

Questa checklist chiude il passaggio da “implementato” a “operativo”. Compilarla per ogni
ambiente di produzione e conservare evidenze (report, screenshot o link all'incidente/test).

## 1. Qualità AI e knowledge base

- [ ] Creare un dataset reale del tenant da `backend/evals/dataset.example.jsonl`.
- [ ] Includere domande rispondibili, parafrasi, fuori ambito, richieste umane e small talk.
- [ ] Eseguire la suite con LLM e salvare il report JSON.
- [ ] Ottenere almeno 90% di pass rate e 100% sui casi sensibili definiti dal cliente.
- [ ] Registrare modello, soglie retrieval e data del report.

## 2. Sicurezza e configurazione

- [ ] `STRICT_PRODUCTION_CONFIG=true` e avvio completato senza warning.
- [ ] `CORS_ALLOW_ALL=false`; `PANEL_ORIGINS` e origin di ogni tenant verificati.
- [ ] `ADMIN_API_KEY` e `METRICS_TOKEN` casuali, lunghi almeno 32 caratteri.
- [ ] Docs API disabilitate e `/metrics` non accessibile senza token.
- [ ] Redis condiviso attivo; rate limit chat, ingest e auth verificati.
- [ ] Rotazione dei secret provata e procedura di emergenza documentata.
- [ ] Stripe webhook firmato, email provider e mittente verificati.
- [ ] Webhook WhatsApp firmato, versione Graph supportata, token di verifica e rotazione secret provati.
- [ ] Coppia VAPID configurata; push ricevuto a panel chiuso e click diretto verificato su desktop/mobile.

## 3. Monitoraggio

- [ ] Sentry riceve un errore di prova con release e ambiente corretti, senza PII.
- [ ] Uptime monitor su `/health` con almeno due destinatari.
- [ ] Regole di `deploy/prometheus-alerts.yml` caricate o replicate nel provider scelto.
- [ ] Alert “backend down” e “LLM unavailable” generati e ricevuti end-to-end.
- [ ] Un responsabile e un backup conoscono il runbook in `deploy/MONITORING.md`.

## 4. Backup e disaster recovery

- [ ] Backup del provider database/PITR verificato per il piano attivo.
- [ ] `backup-postgres.sh` schedulato ogni giorno su storage cifrato separato.
- [ ] Retention dei dump verificata e credenziali escluse dai log.
- [ ] Restore completato su database isolato seguendo `BACKUP_AND_RECOVERY.md`.
- [ ] RPO e RTO effettivi registrati e compatibili con gli obiettivi dichiarati.

## 5. GDPR e ciclo di vita dei dati

- [ ] `DATA_RETENTION_DAYS` positivo e coerente con privacy policy/contratti.
- [ ] Export JSON da panel verificato con un indirizzo di prova.
- [ ] Cancellazione completa verificata dopo l'export.
- [ ] Audit delle operazioni GDPR visibile al superadmin.
- [ ] Procedura interna per identificare e rispondere alle richieste privacy definita.

## 6. Onboarding e pagamenti

- [ ] Signup con email reale e verifica indirizzo.
- [ ] Checkout mensile e annuale in Stripe test mode.
- [ ] Webhook attiva piano/trial e cancellazione riporta correttamente al Free.
- [ ] Login, recupero password e rinvio verifica funzionanti.
- [ ] API key copiata nel plugin WordPress senza interventi database.
- [ ] Origin registrato, prima sync completata e primo messaggio verificato.
- [ ] Checklist onboarding nel profilo arriva a 5/5.

## 7. Errori e fallback

- [ ] Provider AI non disponibile: escalation live o ticket fuori orario, senza errore tecnico.
- [ ] Embedding non disponibile: sync mostra errore e retry, senza falso stato “completato”.
- [ ] Azione carrello fallita: nessuna conferma di aggiunta al cliente.
- [ ] Quota esaurita: messaggio dedicato nel widget e upgrade disponibile nel panel.
- [ ] Sessione scaduta: ritorno al login senza perdere o mostrare dati di altri tenant.
- [ ] Email/webhook falliti: richiesta principale completata e errore osservabile.
- [ ] WhatsApp: messaggio inbound, risposta entro 24h e template fuori finestra verificati end-to-end.

## 8. Release

- [ ] Test backend completi con Postgres+pgvector.
- [ ] Build e test panel verdi.
- [ ] Plugin zip generato, versione/changelog coerenti e smoke test su WordPress reale.
- [ ] Migrazioni provate in upgrade e backup pre-release disponibile.
- [ ] Versione/commit visibile in `/admin/health`.
- [ ] Piano di rollback e responsabile della finestra di rilascio definiti.

Il go-live è approvato solo quando tutti i punti applicabili sono spuntati o una deroga è
documentata con rischio, responsabile e scadenza.
