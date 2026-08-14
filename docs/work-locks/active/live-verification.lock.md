---
block: live-verification
owner: claude
started_at: 2026-08-14T02:10:00+02:00
expires_at: 2026-08-15T02:10:00+02:00
branch: main
---

Obiettivo: chiudere le righe del backlog che dicono «implementato, verifica live da eseguire»
eseguendole davvero, e correggere una riga che è rimasta indietro rispetto al codice.

Cosa faccio:

- **Hardening produzione**: far girare `production_config.production_warnings()` contro le
  variabili vere del servizio, invece di leggerle a occhio. Il valore del controllo è che è **il
  nostro**: se un giorno aggiungiamo una regola, questa verifica la applica da sé.
- **Monitoraggio**: dire cosa è acceso e cosa no, invece di lasciare «da verificare». `/metrics`
  senza token è spento, `/docs` è spento, `/health` risponde.
- **Assistente dentro il panel**: la riga dice ancora «Pianificato» mentre la funzione è in
  produzione da stanotte. È un debito che ho creato io: la regola 7 vuole il backlog aggiornato
  nello stesso commit della feature.

Perimetro previsto:
- `docs/competitor-feature-backlog.md`
- `docs/production-gaps.md` se serve annotare l'esito

Fuori perimetro: codice, e ogni modifica alla configurazione di produzione che non sia il
segreto già impostato.
