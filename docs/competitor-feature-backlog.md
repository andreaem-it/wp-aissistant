# WP AIssistant — Backlog competitivo

> Ricostruito il 31 luglio 2026 a partire dallo stato reale del repository.
> Non è la trascrizione della precedente analisi dei concorrenti, che non era stata salvata:
> è una nuova baseline verificabile da mantenere aggiornata insieme al prodotto.

## Obiettivo

Portare WP AIssistant da assistente WordPress/WooCommerce già funzionante a piattaforma di
supporto AI competitiva con le principali categorie del mercato: AI customer support,
live-chat/help desk, chatbot commerce e automazione omnicanale.

Le priorità usano questa scala:

- **P0 — produzione:** necessaria per vendere e operare il prodotto con affidabilità.
- **P1 — differenziazione:** aumenta nettamente conversione, retention o qualità operativa.
- **P2 — espansione:** amplia mercato, canali o casi d'uso dopo la stabilizzazione.
- **P3 — esplorazione:** investimento importante da validare prima con un prototipo.

## Baseline già disponibile

Queste funzionalità esistono già e non vanno reinserite come nuove feature:

- Chat AI RAG ancorata ai contenuti del sito, streaming e blocco delle domande fuori ambito.
- Sincronizzazione automatica di pagine, articoli e prodotti; upload di documenti, immagini
  con OCR e testo libero.
- Ricerca prodotti, card WooCommerce, aggiunta al carrello verificata e lookup sicuro degli
  ordini con verifica dell'identità.
- Escalation a operatore, ticket, storico completo, risposta via widget/email, indicatore di
  digitazione e webhook di notifica.
- Orari del supporto umano basati sul fuso WordPress e proposta di ticket fuori orario solo
  quando avviene davvero un'escalation.
- Inbox operatore, risposte predefinite, campi informativi, feedback sulle risposte e funzione
  per trasformare una risposta dell'operatore in conoscenza.
- Persistenza della conversazione tra refresh e navigazione, widget personalizzabile,
  animazioni accessibili, disclosure AI e privacy policy configurabile.
- Multi-tenant, autenticazione operatori, isolamento delle conversazioni, rate limit,
  osservabilità, audit superadmin, piani mensili/annuali e billing Stripe.
- Panel e sito statico distribuiti su Cloudflare; backend e database di produzione separati.

## Backlog prioritario

### P0 — Rendere il prodotto production-ready

| Feature | Stato | Impatto | Complessità | Criterio di completamento |
|---|---|---:|---:|---|
| Valutazione sistematica RAG | Implementata, dataset tenant da popolare | Alto | Media | Suite live in `backend/evals/`: dataset per tenant, metriche retrieval e answer quality, soglia CI e regression test. |
| Monitoraggio e alerting operativo | Implementato, destinatari live da verificare | Alto | Media | Sentry, uptime, metriche e regole alert per down/5xx/latenza/ingest/provider AI con runbook. |
| Backup, restore e disaster recovery | Strumenti pronti, scheduling da attivare | Alto | Media | Runbook, dump validato e restore protetto in `deploy/`; resta da schedulare e provare sul database isolato. |
| Hardening produzione | Implementato nel codice, configurazione live da verificare | Alto | Bassa | Validazione fail-closed con `STRICT_PRODUCTION_CONFIG`, warning in admin health e stack production sicuri. |
| Retention ed export GDPR end-to-end | Implementata | Alto | Media | Retention automatica, cancellazione ed export JSON tenant-scoped con audit e flusso guidato nel panel. |
| Onboarding self-service completo | Implementato, verifica live da eseguire | Alto | Media | Signup, verifica, billing e checklist reale per collegamento plugin, prima sync e prima chat. |
| Gestione errori visibile al cliente | Implementata, matrice live da verificare | Medio | Bassa | Fallback AI, retry ingest, quota dedicata e azioni commerce verificate; casi raccolti nella checklist P0. |

### P1 — Funzionalità competitive ad alto rendimento

| Feature | Perché conta | MVP consigliato | Complessità |
|---|---|---|---:|
| Inbox con assegnazione, team e reparti | **Rilasciata:** assegnatario, reparto, priorità, filtri, ordinamenti e viste salvate personali/condivise. | — | Media |
| SLA e regole di instradamento | **Rilasciata:** regole SLA per reparto/priorità, scadenze prima risposta e risoluzione con stato `ok`/`in scadenza`/`violato`, round-robin sui membri del reparto con fallback alla coda, alert+metriche sulle violazioni e filtri nell'inbox. | Prossimo passo: pausa SLA fuori orario di supporto. | Media |
| Note interne, menzioni e collision detection | **Rilasciata:** note interne tenant-scoped mai esposte al visitatore, menzioni `@nome` con stato di lettura, presenza sulla conversazione con avviso di risposta in corso e registro azioni per conversazione. | Prossimo passo: notifica push/email sulle menzioni. | Media |
| Tag e classificazione automatica | **Rilasciata:** tag manuali tenant-scoped con associazione multipla e filtri, classificazione AI (intento/argomento/urgenza) in coda dopo l'escalation o su richiesta, vocabolario chiuso e fallback che lascia la conversazione non classificata. Report per tag e intento in `/stats`. | Prossimo passo: regole automatiche basate sui tag. | Media |
| CSAT post-conversazione | **Rilasciata:** voto 1–5 con commento facoltativo chiesto dal widget alla chiusura, distinto dal feedback sul singolo messaggio; report per AI/operatore/reparto/periodo con distribuzione e ultimi commenti. | Prossimo passo: invito al CSAT anche via email dopo un ticket. | Bassa |
| Workflow no-code | **Rilasciata:** regole per tenant con 7 trigger, condizioni su vocabolario chiuso e 9 azioni (priorità, reparto, assegnazione anche a turno, tag, chiusura, escalation, email, webhook), anteprima a secco, log delle esecuzioni e guardia anti-cascata. | Prossimo passo: azioni ritardate (es. «dopo 24h senza risposta»). | Alta |
| Messaggi proattivi contestuali | **Rilasciata:** quattro trigger (URL, tempo sulla pagina, intento di uscita, carrello), valutazione nel browser, frequenza configurabile, opt-out permanente del visitatore e contatori impression/chat aperte per regola. | Prossimo passo: A/B test fra due messaggi sulla stessa regola. | Media |
| Lead capture e qualificazione | **Rilasciata:** form dinamici per tenant (4 tipi di campo), consenso registrato con il lead, punteggio come somma dei punti dei campi compilati, elenco filtrabile, export CSV protetto da CSV injection ed evento webhook `lead.captured`. | Prossimo passo: connettori CRM diretti (HubSpot/Pipedrive). | Media |
| Multilingua automatica | Necessaria per clienti internazionali. | Rilevamento lingua, risposta nella lingua dell'utente, testi widget localizzati e KB cross-language testata. | Media |
| Analytics avanzate e suggerimenti KB | Rende misurabile il ROI e guida il miglioramento. | Deflection, resolution rate, first response time, temi senza risposta, gap KB e trend. | Alta |
| API pubblica e webhooks gestibili | **Rilasciata:** API `/v1` versionata, chiavi scoped e revocabili con rate limit dedicato, webhook firmati HMAC con retry a backoff, log consegne nel panel e guardia SSRF. Documentazione in [`public-api.md`](public-api.md). | Prossimo passo: eventi su messaggio del visitatore e replay di una consegna dal panel. | Media |

### P2 — Espansione di canale e piattaforma

| Feature | Sequenza consigliata | Complessità |
|---|---|---:|
| Email come canale conversazionale | Prima estensione omnicanale: ingest email, threading, risposta dal panel. | Alta |
| WhatsApp Business | Dopo inbox/assignment e API: template, consenso, finestre di risposta e allegati. | Alta |
| Instagram/Facebook Messenger | Dopo il modello canale unificato introdotto per email/WhatsApp. | Alta |
| Integrazioni CRM | HubSpot/Pipedrive come primi connettori, poi Salesforce in base alla domanda. | Alta |
| Integrazioni help desk | Import/export e handoff con Zendesk, Freshdesk o Intercom per clienti già strutturati. | Alta |
| Notifiche push/PWA operatore | Dopo presenza, assegnazione e SLA; utile per team senza panel sempre aperto. | Media |
| SDK/widget headless | API e componenti per siti non WordPress, mantenendo il plugin come canale principale. | Alta |
| Marketplace e connettori | Solo dopo API/webhook stabili e modello di permessi definito. | Alta |

### P3 — Voice AI

La voce resta un filone separato e trasformativo. La fonte operativa è
[`voice-roadmap.md`](voice-roadmap.md). L'ordine resta:

1. PoC della latenza e qualità italiana con un singolo numero.
2. Inbound AI con RAG e trascrizione nel panel.
3. Escalation con warm transfer o callback/ticket fuori orario.
4. Lookup ordine verificato via voce.
5. Console operatore, coda chiamate e statistiche.
6. Outbound, billing a minuti e compliance telefonica.

Non iniziare lo sviluppo esteso prima del go/no-go sulla latenza del PoC.

## Sequenza di sviluppo raccomandata

### Ciclo 1 — Affidabilità e misurazione

1. Evaluation suite RAG e regression set.
2. Alerting, backup/restore e hardening produzione.
3. Funnel di onboarding completo e verificato.
4. Retention/export GDPR.

### Ciclo 2 — Help desk competitivo *(completato)*

1. ✅ Modello team/reparti e assegnazione.
2. ✅ Priorità, SLA, routing e viste salvate.
3. ✅ Note interne, menzioni e collision detection.
4. ✅ Tag automatici e CSAT.

### Ciclo 3 — Automazione e crescita

1. ✅ API pubblica e webhooks firmati.
2. ✅ Workflow builder su trigger/condizioni/azioni.
3. ✅ Messaggi proattivi e lead qualification.
4. Analytics avanzate e rilevamento automatico dei gap della knowledge base.
5. Multilingua.

### Ciclo 4 — Omnicanale

1. Email.
2. WhatsApp Business.
3. Messenger/Instagram.
4. CRM e help desk esterni.

### Ciclo 5 — Voice

Eseguire il PoC e procedere solo se latenza, qualità, costi e compliance hanno esito positivo.

## Metriche per decidere le priorità

Ogni nuova feature dovrebbe muovere almeno una metrica:

- **Activation:** percentuale di account che completa installazione, sync e prima chat utile.
- **AI resolution rate:** conversazioni risolte senza operatore e senza feedback negativo.
- **Escalation quality:** escalation corrette, false escalation e domande fuori ambito bloccate.
- **Time to first response / resolution:** separando AI e operatori.
- **CSAT:** per conversazione, tenant, operatore e tipologia di richiesta.
- **Knowledge gap rate:** domande senza contesto utile o con retrieval insufficiente.
- **Conversion:** lead raccolti e vendite assistite dal widget.
- **Retention:** tenant attivi e volume utile dopo 30/90 giorni.
- **Margine lordo:** ricavi meno AI, embedding, email, storage e costi dei canali.

## Regole di manutenzione

- Ogni feature entra con owner, milestone, criterio di accettazione e metrica obiettivo.
- Lo stato ammesso è: `da validare`, `pianificata`, `in sviluppo`, `beta`, `rilasciata`.
- Una feature è `rilasciata` solo dopo test, telemetria, documentazione e comunicazione cliente.
- Aggiornare questo file nello stesso commit che introduce o chiude una feature rilevante.
- Rivalutare l'ordine trimestralmente usando richieste clienti e dati prodotto, non solo la
  parità nominale con i concorrenti.
