---
block: widget-docs
owner: claude
started_at: 2026-08-14T01:40:00+02:00
expires_at: 2026-08-15T01:40:00+02:00
branch: main
---

Obiettivo: la parte documentale della fase 6. L'integrazione JavaScript è diventata il prodotto
che vendiamo, e la sua documentazione oggi **dice cose false**.

Cosa non torna più, dopo il widget 0.2.0:

- `sdk/widget/README.md` mostra ancora `backendUrl` nello snippet — un'opzione che non esiste
  più — e continua a raccomandare la versione fissa come default, che è la decisione rovesciata
  ieri. Un README sbagliato è peggio di uno assente: chi lo segue ottiene un widget che non parte
  e non ha modo di capire perché.
- Manca `docs/embedded-widget.md`, che la roadmap chiede da tre fasi: opzioni, adapter host,
  modello di aggiornamento e nota SRI in un posto solo.
- `docs/handoff.md` indica ancora l'URL grezzo di Railway come backend di produzione.
- La tabella dell'adapter non elenca `chatHeaders()`, aggiunto per l'assistente del pannello.

Regola che vale qui più che altrove: **le opzioni non si riscrivono**. Il vocabolario è dichiarato
in `sdk/widget/src/schema.js` e generato in `schema.json`; la documentazione descrive
comportamenti e decisioni e rimanda a quello, altrimenti diventa la quarta copia della lista —
il debito 5 dell'handoff, in forma di prosa.

Fuori perimetro (bloccato, non dimenticato): la pubblicazione su npm. Servono l'organizzazione
`@wp-aissistant` su npm e il secret `NPM_TOKEN`, che richiedono l'account del proprietario. Il
workflow `publish-sdk.yml` è già pronto e aspetta solo quelli.

Perimetro previsto:
- `docs/embedded-widget.md` (nuovo)
- `sdk/widget/README.md`
- `docs/handoff.md` (l'indirizzo del backend)
- `docs/embedded-assistant-roadmap.md` (stato della fase 6)

Fuori perimetro: codice di widget, backend, pannello e plugin.
