# Lock: il testo del prodotto non è tracciato in sincronizzazione

**Area**: `wp-plugin/wp-aissistant/wp-aissistant.php`, `assets/admin-sync.js`
**Aperto**: 2026-08-08

Un prodotto produce due invii: la scheda (card) e il testo (ciò da cui il modello risponde).
Il secondo è fire-and-forget e il suo esito viene buttato: se fallisce, la riga dice
"sincronizzato" e il prodotto resta in base senza descrizione, senza che nulla lo segnali.
Inoltre il contatore finale conta come riuscite anche le righe finite in errore.
