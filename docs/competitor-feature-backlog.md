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
| Valutazione sistematica RAG | Parziale | Alto | Media | Dataset di domande attese/fuori ambito per tenant, metriche retrieval e answer quality, soglie documentate e regression test. |
| Monitoraggio e alerting operativo | Parziale | Alto | Media | Alert su error rate, latenza, coda ingest, provider AI, email e webhook; runbook e storico incidenti. |
| Backup, restore e disaster recovery | Da fare | Alto | Media | Backup automatici verificati, prova di ripristino e RPO/RTO dichiarati. |
| Hardening produzione | Parziale | Alto | Bassa | CORS ristretto, domini definitivi, secret rotation, endpoint tecnici protetti e checklist release. |
| Retention ed export GDPR end-to-end | Parziale | Alto | Media | Policy per tenant, cancellazione automatica, export conversazioni/contatti e audit delle richieste privacy. |
| Onboarding self-service completo | Parziale | Alto | Media | Signup → verifica email → pagamento → connessione plugin → prima sync → test widget, senza intervento manuale. |
| Gestione errori visibile al cliente | Parziale | Medio | Bassa | Stati chiari per backend/AI/ingest indisponibili, retry sicuri e nessuna conferma di azioni non riuscite. |

### P1 — Funzionalità competitive ad alto rendimento

| Feature | Perché conta | MVP consigliato | Complessità |
|---|---|---|---:|
| Inbox con assegnazione, team e reparti | Porta il panel da semplice coda a vero help desk. | Assegnatario, reparto, priorità, stato, filtri e viste salvate. | Media |
| SLA e regole di instradamento | Riduce tempi di risposta e rende il prodotto adatto a team strutturati. | SLA per piano/reparto, round-robin, alert di scadenza e fallback. | Media |
| Note interne, menzioni e collision detection | Evita risposte doppie e migliora la collaborazione. | Note non visibili al cliente, `@mention`, presenza operatore e lock/composer warning. | Media |
| Tag e classificazione automatica | Abilita report e automazioni realmente utili. | Tag manuali + classificazione AI per intento, tema e urgenza. | Media |
| CSAT post-conversazione | Misura l'esito del supporto, non solo il singolo messaggio AI. | Voto 1–5, commento opzionale, report per AI/operatore/canale. | Bassa |
| Workflow no-code | È una lacuna forte rispetto ai prodotti maturi. | Trigger, condizioni e azioni per escalation, tag, assegnazione, webhook ed email. | Alta |
| Messaggi proattivi contestuali | Aumenta conversioni e riduce abbandono. | Trigger per URL, tempo sulla pagina, carrello e intento di uscita; frequenza limitata e consenso. | Media |
| Lead capture e qualificazione | Trasforma il widget anche in strumento commerciale. | Form dinamici, consenso, scoring base, export CSV e webhook CRM. | Media |
| Multilingua automatica | Necessaria per clienti internazionali. | Rilevamento lingua, risposta nella lingua dell'utente, testi widget localizzati e KB cross-language testata. | Media |
| Analytics avanzate e suggerimenti KB | Rende misurabile il ROI e guida il miglioramento. | Deflection, resolution rate, first response time, temi senza risposta, gap KB e trend. | Alta |
| API pubblica e webhooks gestibili | Sblocca CRM, automation platform e integrazioni proprietarie. | API versionata, chiavi scoped, webhook firmati, retry, log consegne e documentazione. | Media |

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

### Ciclo 2 — Help desk competitivo

1. Modello team/reparti e assegnazione.
2. Priorità, SLA, routing e viste salvate.
3. Note interne, menzioni e collision detection.
4. Tag automatici e CSAT.

### Ciclo 3 — Automazione e crescita

1. API pubblica e webhooks firmati.
2. Workflow builder su trigger/condizioni/azioni.
3. Messaggi proattivi e lead qualification.
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
