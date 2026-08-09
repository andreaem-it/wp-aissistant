# Lock: correggere il piano segnaposto inventato

**Area**: `backend/app/db.py`, `routers/admin.py`, `routers/commercial.py`, `alembic/0053`,
`panel/src/Admin.jsx`
**Aperto**: 2026-08-09

La migrazione 0052 ha rinominato il piano "Free" in "Base" e gli ha messo un prezzo di 1 €
lasciando `monthly_message_limit = 0` (illimitato). È diventato un prodotto apparente che
svuota di senso il piano da 19 €/500 messaggi, non esiste su Stripe e non è pubblicizzato.

Quella riga è un segnaposto interno per gli account che non hanno ancora pagato, non un
piano. Va marcata come interna, tenuta fuori da ogni elenco rivolto ai clienti, e non deve
avere un prezzo che la faccia sembrare acquistabile.

Manca inoltre la modifica dei piani dal pannello: esiste l'endpoint, non l'interfaccia.
