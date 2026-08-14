---
block: push-key-rotation
owner: claude
started_at: 2026-08-14T19:35:00+02:00
expires_at: 2026-08-16T19:35:00+02:00
branch: main
---

Obiettivo: rendere **sopravvivibile** la rotazione delle chiavi VAPID. Oggi non lo è, e il modo
in cui fallisce è quello peggiore: silenzioso da entrambe le parti.

Trovato mentre valutavo l'impatto di una rotazione (necessaria: ho esposto io la chiave privata
stampando le variabili del servizio — è un valore PEM multilinea e il filtro sui nomi non l'ha
retto).

Due difetti che si coprono a vicenda:

1. **Il pannello riusa una sottoscrizione scaduta.** `enable()` fa
   `current || subscribe({applicationServerKey})`: se una sottoscrizione esiste la tiene, senza
   guardare **con quale chiave** era stata creata. Dopo una rotazione l'operatore preme «attiva»,
   ottiene la vecchia, e l'interruttore mostra «attive» perché `getSubscription()` risponde. Non
   riceverà mai più una notifica e non c'è niente che glielo dica.
2. **Il backend non elimina mai quella sottoscrizione.** `send()` pota su `404/410`, ma una
   chiave che non corrisponde produce `403`: la riga resta in base per sempre e ogni notifica
   spende una richiesta destinata a fallire.

La correzione è nei due punti insieme, perché ognuno da solo lascia l'altro difetto in piedi.

Perimetro previsto:
- `backend/app/push.py` e i suoi test
- `panel/src/Profile.jsx` e i suoi test
- `docs/handoff.md` o backlog, per annotare la procedura di rotazione

Fuori perimetro: la rotazione vera delle chiavi in produzione, che decide il proprietario —
invalida le sottoscrizioni esistenti, e va fatta sapendo che gli operatori dovranno riattivare.
