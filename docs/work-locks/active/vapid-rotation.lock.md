---
block: vapid-rotation
owner: claude
started_at: 2026-08-15T00:20:00+02:00
expires_at: 2026-08-16T00:20:00+02:00
branch: main
---

Obiettivo: registrare la rotazione delle chiavi VAPID appena eseguita in produzione, e quello
che comporta per gli operatori.

Motivo della rotazione: la chiave privata precedente è stata **esposta da me** in una
trascrizione di lavoro, elencando le variabili del servizio. È un valore PEM multilinea e il
filtro che doveva mostrare i soli nomi non l'ha retto; la verifica successiva ha confermato che
il corpo della chiave era stato stampato per intero.

Fatto finora, fuori dal repository:
- nuova coppia P-256 generata e verificata **prima** di scriverla — `py_vapid` la carica e firma,
  e la pubblica deriva dalla privata;
- entrambe impostate insieme sul servizio, perché separate lascerebbero una finestra in cui non
  corrispondono e nessuna notifica partirebbe;
- coerenza e assenza di avvisi di produzione verificate contro le variabili vere.

Resta da applicare con un deploy: le variabili sono state scritte con `--skip-deploys`.

Perimetro previsto:
- `README.md` (registrare la rotazione nella sezione che l'ha già descritta)
- `docs/handoff.md` (una riga di stato)

Fuori perimetro: codice. La correzione che rende sopravvivibile la rotazione è già rilasciata.
