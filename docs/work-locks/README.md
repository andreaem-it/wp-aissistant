# Lock dei blocchi di lavoro

Questo registro evita che Codex, Claude o una persona implementino lo stesso blocco in
parallelo. I lock sono file versionati: `active/<slug>.lock.md`.

## Acquisizione obbligatoria

1. Aggiorna `main` dal remoto e controlla questa cartella.
2. Se esiste un lock che sovrappone il tuo perimetro, scegli un altro blocco. Non aggirarlo.
3. Crea un lock dal template con proprietario, perimetro, file previsti e scadenza.
4. Crea un **commit contenente solo il lock** e pubblicalo su `main`.
5. Se il push viene rifiutato, riallinea `main` e ricontrolla i lock: il primo lock pubblicato
   vince. Non forzare mai il push.
6. Solo dopo il push riuscito inizia a modificare il prodotto.

## Chiusura e lock scaduti

- La feature e la rimozione del relativo lock devono stare nello stesso commit finale.
- Se il lavoro viene abbandonato, rimuovi il lock con un commit dedicato.
- Un lock scaduto non si cancella alla cieca: verifica branch, commit e stato con il
  proprietario. Se non c'è lavoro recuperabile, sostituiscilo con un nuovo lock spiegandolo
  nel commit.
- Un blocco grande va diviso: il lock deve indicare file e confini concreti, non “backend” o
  “roadmap intera”.

## Template

```md
---
block: nome-stabile-del-blocco
owner: codex | claude | nome-persona
started_at: YYYY-MM-DDTHH:MM:SS+TZ
expires_at: YYYY-MM-DDTHH:MM:SS+TZ
branch: main
---

Obiettivo: risultato verificabile.

Perimetro previsto:
- `path/file`

Fuori perimetro:
- aree che l'altro agente può modificare senza conflitto
```
