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
- Panel tenant riorganizzato per utenti non tecnici: navigazione per obiettivo, sezioni interne a tab, testi operativi coerenti e layout mobile dedicato.

## Backlog prioritario

### P0 — Rendere il prodotto production-ready

| Feature | Stato | Impatto | Complessità | Criterio di completamento |
|---|---|---:|---:|---|
| GDPR e residenza dei dati UE | **Audit completato, remediation P0 in corso** | Alto | Alta | Il 9 agosto backend Railway è stato spostato da `sfo` a EU West, gli allegati da un semplice hint `EEUR` a R2 jurisdiction `eu`, Redis è stato creato in EU West e production strict è stato attivato con zero warning. Per l'AI è pronto un guardrail fail-closed e un piano Mistral EU; mancano account/DPA, chiave e benchmark prima del passaggio live. La retention dei tenant attivi è una scelta configurabile distinta dalla cancellazione completa 90 giorni dopo la disdetta. Restano inoltre registro subprocessori, DPIA e pagine legali. Non usare ancora claim «tutti i dati in UE» o «100% GDPR compliant». Piano ed evidenze in [`gdpr-eu-residency-audit.md`](gdpr-eu-residency-audit.md). |
| Valutazione sistematica RAG | Implementata, dataset tenant da popolare | Alto | Media | Suite live in `backend/evals/`: dataset per tenant, metriche retrieval e answer quality, soglia CI e regression test. |
| Monitoraggio e alerting operativo | Implementato, destinatari live da verificare | Alto | Media | Sentry, uptime, metriche e regole alert per down/5xx/latenza/ingest/provider AI con runbook. |
| Backup, restore e disaster recovery | Strumenti pronti, scheduling da attivare | Alto | Media | Runbook, dump validato e restore protetto in `deploy/`; resta da schedulare e provare sul database isolato. |
| Hardening produzione | Implementato nel codice, configurazione live da verificare | Alto | Bassa | Validazione fail-closed con `STRICT_PRODUCTION_CONFIG`, warning in admin health e stack production sicuri. |
| Retention ed export GDPR end-to-end | Implementata | Alto | Media | Retention automatica, cancellazione ed export JSON tenant-scoped con audit e flusso guidato nel panel. |
| Onboarding self-service completo | Implementato, verifica live da eseguire | Alto | Media | Signup, verifica, billing e checklist reale per collegamento plugin, prima sync e prima chat. |
| Gestione errori visibile al cliente | Implementata, matrice live da verificare | Medio | Bassa | Fallback AI, retry ingest, quota dedicata e azioni commerce verificate; casi raccolti nella checklist P0. |
| Visibilità commerciale (superadmin) | Implementate ricavi, costi, margine e azioni commerciali | Alto | Media | Viste **Ricavi** e **Costi e margine** nel panel admin. Ricavi: MRR/ARR normalizzati sull'intervallo reale di fatturazione, ripartizione per piano, insoluti, prove in scadenza, disdette programmate e del periodo; incassato, a rischio e in prova restano separati. Costi: inferenza, embedding stimati, storage e messaggistica con listini configurabili; componenti e modelli senza prezzo sono esclusi e segnalati, mai considerati gratis. Valute diverse sono dichiarate invece di applicare cambi arbitrari. Azioni commerciali (proroga prova, coupon, sospensione, disdetta, cambio piano) eseguite **su Stripe** con il webhook come unico scrittore dello stato. Funnel di attivazione e clienti a rischio completano la vista. Prossimo passo: popolare e verificare in produzione tutti i listini e definire la conversione contabile USD/EUR. |
| Autonomia dell'abbonamento | Implementata, portale Stripe da configurare in dashboard | Alto | Bassa | Portale Stripe da `/billing/portal` per metodo di pagamento, fatture, cambio piano e disdetta senza passare dal supporto; stato di fatturazione (insoluto, disdetta programmata con data, prova) visibile nel panel; email automatiche su pagamento fallito, prova in scadenza, disdetta registrata e abbonamento terminato. Il periodo è specchiato sul client dal webhook, così `/usage` non chiama Stripe. Setup in [`../deploy/STRIPE.md`](../deploy/STRIPE.md). Prossimo passo: dati fiscali italiani (P.IVA/SDI) al checkout. |

### P1 — Funzionalità competitive ad alto rendimento

| Feature | Perché conta | MVP consigliato | Complessità |
|---|---|---|---:|
| Inbox con assegnazione, team e reparti | **Rilasciata:** assegnatario, reparto, priorità, filtri, ordinamenti e viste salvate personali/condivise. | — | Media |
| SLA e regole di instradamento | **Rilasciata:** regole SLA per reparto/priorità, scadenze prima risposta e risoluzione con stato `ok`/`in scadenza`/`violato`, round-robin sui membri del reparto con fallback alla coda, alert+metriche sulle violazioni e filtri nell'inbox. Il calendario lavorativo tenant-scoped mette in pausa entrambe le scadenze fuori orario, è DST-safe, calcola automaticamente le festività nazionali italiane, gestisce chiusure straordinarie e sincronizza giorni/orari/fuso WordPress tramite installazione verificata con challenge HMAC. | Prossimo passo: calendari nazionali aggiuntivi per l'espansione internazionale. | Media |
| Note interne, menzioni e collision detection | **Rilasciata:** note interne tenant-scoped mai esposte al visitatore, menzioni `@nome` con stato di lettura, presenza sulla conversazione con avviso di risposta in corso e registro azioni per conversazione. | Prossimo passo: notifica push/email sulle menzioni. | Media |
| Tag e classificazione automatica | **Rilasciata:** tag manuali tenant-scoped con associazione multipla e filtri, classificazione AI (intento/argomento/urgenza) in coda dopo l'escalation o su richiesta, vocabolario chiuso e fallback che lascia la conversazione non classificata. Report per tag e intento in `/stats`. | Prossimo passo: regole automatiche basate sui tag. | Media |
| CSAT post-conversazione | **Rilasciata:** voto 1–5 con commento facoltativo chiesto dal widget alla chiusura, distinto dal feedback sul singolo messaggio; report per AI/operatore/reparto/periodo con distribuzione e ultimi commenti. | Prossimo passo: invito al CSAT anche via email dopo un ticket. | Bassa |
| Workflow no-code | **Rilasciata:** regole per tenant con 7 trigger, condizioni su vocabolario chiuso e 10 azioni. L'azione «Attendi» salva la continuazione nel database, la esegue via worker con retry e può annullarla quando arriva una risposta; stato ed errori sono visibili nello storico. Restano anteprima a secco, log e guardia anti-cascata. | Prossimo passo: completato il blocco previsto; rivalutare dai dati reali. | Alta |
| Messaggi proattivi contestuali | **Rilasciata:** quattro trigger, frequenza configurabile, opt-out, A/B test stabile, metriche separate, vincitore al 95%, promozione con un clic, interruzione sicura e storico immutabile con audit operatore. | Prossimo passo: completato il blocco previsto; rivalutare dai dati reali. | Media |
| Lead capture e qualificazione | **Rilasciata:** form dinamici per tenant (4 tipi di campo), consenso registrato con il lead, punteggio come somma dei punti dei campi compilati, elenco filtrabile, export CSV protetto da CSV injection ed evento webhook `lead.captured`. **Fondazione CRM pronta per il mercato italiano:** collegamenti tenant-scoped Brevo/Zoho/Pipedrive, invio manuale idempotente, stato nel panel e Worker Cloudflare provider-aware. | Prossimo passo: consenso OAuth self-service e mapping personalizzato dei campi. | Media |
| Multilingua automatica | **Rilasciata:** rilevamento deterministico a ogni messaggio (6 lingue) con il locale del browser come solo suggerimento, risposta nella lingua del visitatore anche su knowledge base in altra lingua, risposte deterministiche tradotte a template, catalogo testi del widget separato e testato, filtro lingua nell'inbox e ripartizione nelle statistiche. | Prossimo passo: traduzione assistita dei contenuti KB per le lingue più richieste. | Media |
| Analytics avanzate e suggerimenti KB | **Rilasciata:** deflection per conversazione, tempi di prima risposta e risoluzione, trend, gap con clustering semantico locale e flusso «insegna». I cluster generano ora bozze persistenti privacy-first senza inviare conversazioni a provider esterni; l'operatore deve completare i segnaposto, può pubblicare con un clic e confronta occorrenze precedenti e nuove lacune dopo la pubblicazione. | Prossimo passo: rivalutare qualità e impatto su dati reali. | Alta |
| API pubblica e webhooks gestibili | **Rilasciata:** API `/v1` versionata, chiavi scoped e revocabili con rate limit dedicato, webhook firmati HMAC con retry a backoff, payload con schema `1.0`, eventi omnicanale privacy-safe, log filtrabile/paginato con JSON, replay manuale, metriche a 30 giorni, alert automatico sugli endpoint degradati e guardia SSRF. Documentazione in [`public-api.md`](public-api.md). | Prossimo passo: completato il blocco previsto; rivalutare dai dati reali. | Media |

### P2 — Espansione di canale e piattaforma

| Feature | Sequenza consigliata | Complessità |
|---|---|---:|
| Email come canale conversazionale | **Rilasciata nel backend:** adapter inbound indipendente dal provider, deduplicazione dei webhook, threading, contatto unificato, ticket/SLA e risposta diretta dal panel con header email di thread. Resta il setup del webhook presso il provider scelto. | Alta |
| WhatsApp Business | **Beta nel prodotto:** adapter provider-neutral, contatto/thread unificato, deduplicazione, ticket/SLA, finestra di 24 ore, consenso tracciato e template approvati dal panel. Worker Meta firmato e multi-tenant pronto al deploy; restano credenziali/numero live, sincronizzazione catalogo template e file allegati. | Alta |
| Allegati conversazione | **Rilasciata:** upload operatore dal panel, storage privato Cloudflare R2, download autenticato, isolamento tenant e cancellazione GDPR. **Media inbound:** i tre canali (email, WhatsApp, Messenger/Instagram) accettano allegati come byte base64 già scaricati dall'adapter — nessun token provider e nessuna URL remota nel backend — con whitelist dei formati, limiti per file e per messaggio, rifiuto integrale dei payload malformati, messaggi con solo media e nessuna perdita del messaggio se lo storage è giù. Anteprima immagini nell'inbox da object URL autenticato, mai da URL pubblica. **Worker allineati:** l'adapter WhatsApp risolve il media id con il token del tenant (inviato solo agli host Meta, URL di download validato) e l'email router estrae gli allegati MIME ignorando loghi di firma; entrambi troncano ai limiti del backend dichiarando nel corpo cosa non è stato inoltrato. Prossimo passo: Worker Messenger/Instagram e verifica end-to-end con credenziali live. | Media |
| Instagram/Facebook Messenger | **Beta nel prodotto:** adapter inbound condiviso e provider-neutral, deduplicazione, threading, contatto unificato, ticket/SLA e risposta operatore tramite adapter tenant-aware. **Worker Meta rilasciato** (`cloudflare/meta-messaging-adapter`): firma HMAC verificata, mapping pagina/account IG → tenant senza credenziali nel database, echo dei propri invii scartati, postback con id stabile, allegati scaricati dal CDN firmato senza token e troncati ai limiti del backend, invio operatore sulla Send API. Restano credenziali live, revisione dell'app Meta e verifica end-to-end. | Alta |
| Integrazioni CRM | **Fondazione rilasciata:** configurazione Brevo/Zoho/Pipedrive per tenant senza segreti nel database, invio esplicito dei lead, retry idempotente, stato visibile nel panel e Worker Cloudflare con deduplicazione per email. Restano OAuth self-service, mapping campi e sincronizzazione automatica asincrona; TeamSystem va aggiunto appena verificata la disponibilità delle API partner. | Alta |
| Integrazioni help desk | **Fondazione rilasciata:** connessioni Zendesk/Freshdesk tenant-scoped, handoff manuale idempotente con contatto e transcript completo, stato e retry nel panel, credenziali isolate in un adapter esterno. Il panel offre una coda ticket a due pannelli, ricerca per numero/motivo/email, viste per stato e configurazione helpdesk separata dal lavoro quotidiano. Restano configurazione guidata delle credenziali provider, sincronizzazione bidirezionale e Intercom. | Alta |
| Notifiche push/PWA operatore | **Rilasciata:** panel installabile, sottoscrizioni multi-dispositivo per operatore, preferenze e push su escalation, assegnazioni, menzioni e violazioni SLA; click diretto sulla conversazione e rimozione automatica endpoint scaduti. | Media |
| SDK/widget headless | **Fondazione rilasciata:** client browser framework-agnostic con sessione persistente, chat sincrona e streaming SSE, polling, feedback, contatto, ticket, CSAT e lead form; Web Component accessibile e isolato in Shadow DOM; token conversazione mai nella URL e HTTPS obbligatorio. **Pacchetto npm pronto:** `@wp-aissistant/browser` con tipi TypeScript inclusi, licenza MIT, contenuto del tarball bloccato da test e pubblicazione da tag `sdk-v*` con provenance firmata. Resta la pubblicazione effettiva: scope npm, secret `NPM_TOKEN` e primo tag ([procedura](browser-sdk.md#pubblicazione-su-npm)). | Alta |
| Licenza legata al dominio | **Rilasciata e applicata.** Una licenza copre un sito: un dominio live (`Plan.max_live_origins`, 1 di default), uno di staging vincolato a sottodominio del live con etichetta di sviluppo — confrontata **per etichetta DNS, mai per sottostringa** — o a una piattaforma riconosciuta, e indirizzi locali illimitati e non contati. Applicazione **fail closed** in `deps.rate_limit_chat`: senza dominio registrato o senza header `Origin` non si passa, chiudendo il varco dell'uso server-side di una chiave pubblica. `ClientOrigin` è la sorgente di verità per licenza, CORS e callback dell'order lookup; `Client.allowed_origins` resta come specchio per il solo pannello admin. Registrazione self-service da `/account/origins` con slot visibili, cambio del dominio live con raffreddamento e audit, e **bootstrap dall'installazione WordPress**: il challenge HMAC registra il dominio da sé, così l'onboarding non richiede il superadmin. **Visibile**: schermata «Siti e licenza» nel pannello (domini, slot, domini visti in uso, conferma esplicita prima di sostituire il dominio di produzione) e widget che, su un 403 di licenza, scrive il motivo in console per chi installa e mostra al visitatore un testo neutro che non invita a riprovare — verificato in sei lingue che non citi licenza, dominio o codici di errore. | Alta |
| Widget standalone e CDN | **Estrazione rilasciata:** il widget vive in `sdk/widget`, si costruisce con esbuild in un bundle senza dipendenze e il plugin WordPress lo carica invece di possederlo, riducendosi a produttore di opzioni più un adapter WooCommerce (carrello, identità, frammenti). Vocabolario delle opzioni dichiarato una volta sola in `schema.js`, con fallback al default per i valori fuori lista. Test di montaggio in jsdom come rete dell'estrazione. **Distribuzione preparata**: pubblicazione su R2 (non Pages: `pages deploy` sostituisce la produzione, mentre una versione immutabile deve restare viva per anni) con percorsi versionati, SRI calcolata dalla build e verifica che il file sia davvero raggiungibile da un browser; il plugin carica dal CDN con `integrity` e ripiego automatico sulla copia nel pacchetto. **Attiva**: `cdn.wpaissistant.it/widget/0.1.0/` pubblicato e verificato (impronta del file servito uguale all'SRI di build), plugin che punta al CDN sulla versione fissa con ripiego automatico. L'ordine di rilascio è vincolante — prima il tag del widget, poi la release del plugin — e `build.sh` avvisa se la versione impacchettata non è pubblicata. **Configuratore rilasciato**: schermata *Impostazioni → Installazione* con la scelta esplicita fra plugin e JavaScript, controlli costruiti dal vocabolario del backend, anteprima che monta il widget vero in modalità anteprima (disegna tutto, non chiama niente) e snippet generato con le sole opzioni cambiate rispetto ai default. **Configurazione lato server rilasciata**: `WidgetConfig` per tenant (migrazione 0056) con aspetto e testi validati contro il vocabolario **condiviso** con il widget — `sdk/widget/schema.json` è generato dalla build e letto dal backend, con un test che fallisce quando l'artefatto versionato e lo schema divergono, così la lista resta una sola in tre linguaggi. Un valore fuori vocabolario viene rifiutato con il motivo, non corretto in silenzio: il widget ripiega perché deve funzionare comunque, il configuratore no. **Parità JavaScript/plugin (0.2.0)**: sei difetti trovati da uno screenshot, tutti della stessa famiglia — cose che il plugin forniva e il bundle no. Icone SVG dentro il bundle invece di Font Awesome caricata dalla pagina ospite (che le rendeva invisibili in ogni installazione JavaScript), avatar con iniziale invece di un'immagine rotta, testi annidati dello snippet non più ignorati in silenzio, avatar e link privacy finalmente configurabili. **Lo snippet punta a un percorso stabile** (`/widget/v1/`), non a una versione: uno snippet incollato nel sito di un cliente non si può riscrivere, quindi la versione dentro l'URL rendeva impossibile correggere un difetto. Il costo è dichiarato — niente SRI su un percorso che cambia — e il plugin resta pinnato con SRI perché ha copia locale e canale suo. **`backendUrl` non è più un'opzione**: compilato nell'artefatto, così l'indirizzo non resta congelato nelle pagine altrui. **Update server rilasciato (plugin 1.4.0)**: lo zip su `cdn.wpaissistant.it/plugin/<versione>/` come il widget, `GET /plugin/update` che ne dichiara versione e requisiti, e il plugin che interroga con `pre_set_site_transient_update_plugins` più `plugins_api` per la scheda dei dettagli. Il manifest è pubblico di proposito — chiuderlo dietro la chiave toglierebbe le correzioni di sicurezza proprio a chi ha la licenza scaduta — e il dominio dello zip è fissato nel plugin, perché WordPress *esegue* ciò che scarica. La versione è dichiarata in cinque posti e un test più un controllo nel workflow impediscono che divergano. La 1.4.0 va installata a mano una volta: le versioni precedenti non sanno cercare aggiornamenti ([roadmap](embedded-assistant-roadmap.md)). | Alta |
| Assistente dentro il panel | Pianificato: il widget nel panel del cliente con la nostra knowledge base e il contesto del tenant loggato, derivato dal backend a partire da un token firmato e non dal browser. Vedi [roadmap](embedded-assistant-roadmap.md). | Media |
| Tenant interno e piano illimitato | **Rilasciato.** Piano `internal_unlimited` (migrazione 0055): non vendibile, invisibile ai clienti, messaggi e domini illimitati, limiti di frequenza alzati perché dietro un solo `client_id` passerà il traffico di tutti i pannelli. `Plan.code` sostituisce la scelta per id più basso in `default_plan_id()`: senza, su un database in cui il piano illimitato nasce per primo ogni nuovo iscritto avrebbe ricevuto accesso illimitato. I nostri tenant sono esclusi da ricavi, funnel di attivazione e clienti a rischio, e la loro spesa è dichiarata a parte come costo di piattaforma (`internal_cost_cents`) invece di sparire dal margine — il segnaposto resta invece dentro le viste, perché chi non ha ancora pagato è un cliente da attivare. Resta da creare il nostro tenant in produzione. | Alta |
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

### Ciclo 3 — Automazione e crescita *(completato)*

1. ✅ API pubblica e webhooks firmati.
2. ✅ Workflow builder su trigger/condizioni/azioni.
3. ✅ Messaggi proattivi e lead qualification.
4. ✅ Analytics avanzate e rilevamento automatico dei gap della knowledge base.
5. ✅ Multilingua.

### Ciclo 3.1 — Ottimizzazione dai dati *(completato)*

1. ✅ Clustering semantico locale dei gap KB.
2. ✅ A/B test, vincitore statistico e storico dei messaggi proattivi.
3. ✅ Azioni differite persistenti nei workflow.
4. ✅ Bozze di articoli KB privacy-first con revisione, pubblicazione e misura dell'impatto.

### Prossimo ciclo consigliato

1. OAuth self-service e mapping personalizzato dei campi CRM.
2. Allegati inbound e visualizzazione inline sicura, quando saranno attivati i canali live.
3. WhatsApp Business live, quando saranno disponibili numero e credenziali Meta.

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
