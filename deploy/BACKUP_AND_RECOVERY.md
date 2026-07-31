# Backup, restore e disaster recovery

## Obiettivi iniziali

- **RPO:** massimo 24 ore di dati persi con dump giornaliero; ridurlo usando il point-in-time
  recovery del provider database quando il piano lo consente.
- **RTO:** ripristino del servizio entro 2 ore per un incidente database ordinario.
- Conservazione: 14 backup giornalieri e almeno una copia in uno storage separato dal database.

I backup del provider sono il primo livello, ma non sostituiscono un export indipendente e una
prova periodica di restore.

## Backup applicativo

Il job richiede i client PostgreSQL (`pg_dump`, `pg_restore`) della stessa major version del
server o più recenti.

```bash
DATABASE_URL='postgresql://…' \
BACKUP_DIR='/percorso/storage-separato' \
BACKUP_RETENTION_DAYS=14 \
bash deploy/scripts/backup-postgres.sh
```

Lo script produce un dump custom compresso, lo valida con `pg_restore --list`, pubblica il
file solo dopo il controllo e rimuove i dump locali oltre retention. Pianificarlo ogni giorno
con il sistema di scheduling disponibile e copiare il risultato in storage cifrato separato.
Non salvare `DATABASE_URL` nel repository o nell'output del job.

## Restore sicuro

Provare il restore su un database vuoto e isolato, mai direttamente sulla produzione:

```bash
export TARGET_DATABASE_URL='postgresql://…/wpai_restore_test'
export CONFIRM_TARGET_DATABASE_URL="$TARGET_DATABASE_URL"
bash deploy/scripts/restore-postgres.sh backups/wp-aissistant-YYYYMMDDTHHMMSSZ.dump
```

La doppia variabile è una protezione contro restore accidentali. Dopo il restore:

1. eseguire `alembic current` e confrontarlo con `alembic heads`;
2. avviare una sola istanza backend collegata al database di prova;
3. controllare `/health` e `/admin/health`;
4. verificare conteggi di client, conversazioni, messaggi, chunk, prodotti e operatori;
5. eseguire una query RAG e un login operatore senza inviare email/webhook reali;
6. eliminare il database di prova solo dopo aver registrato esito e tempi.

## Runbook incidente

1. Dichiarare l'incidente e fermare temporaneamente scritture/worker se il database è corrotto.
2. Identificare l'ultimo punto valido usando log, audit e dashboard del provider.
3. Preferire il point-in-time recovery su una nuova istanza; altrimenti usare l'ultimo dump.
4. Validare lo schema e gli smoke test sulla nuova istanza.
5. Aggiornare `DATABASE_URL`, avviare una sola replica e verificare i flussi principali.
6. Riattivare worker e traffico, monitorando errori e coda ingest.
7. Documentare durata, perdita dati effettiva, causa e azioni preventive.

## Verifica periodica

- Ogni giorno: job completato, file non vuoto e copia nello storage secondario.
- Ogni mese: restore automatico o manuale su database isolato.
- Ogni trimestre: simulazione completa e misura di RPO/RTO.
- Dopo migrazioni importanti: backup pre-release e prova di downgrade/restore.

Un backup non è considerato valido finché almeno un restore non è stato completato con successo.
