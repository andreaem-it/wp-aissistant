# WP AIssistant

![CI](https://github.com/andreaem-it/wp-aissistant/actions/workflows/ci.yml/badge.svg)

Assistente AI di supporto clienti per siti WordPress / WooCommerce, basato su RAG.
Un widget di chat flottante risponde ai visitatori usando i contenuti del sito come
knowledge base, ed effettua l'escalation a un operatore umano quando la richiesta
esce dal suo perimetro (rimborsi, reclami, modifiche account, domande fuori contesto).

> **Stato:** MVP funzionante. Vedi [Roadmap MVP → Produzione](#roadmap-mvp--produzione)
> per i lavori necessari prima del rilascio in produzione.
> La roadmap di prodotto aggiornata è in
> [`docs/competitor-feature-backlog.md`](docs/competitor-feature-backlog.md).
> Il lavoro parallelo tra agenti usa i lock versionati descritti in
> [`docs/work-locks/README.md`](docs/work-locks/README.md).

## Architettura

Componenti indipendenti, collegati da API autenticate:

```
┌─────────────────┐        ┌──────────────────────┐        ┌─────────────────┐
│  wp-plugin      │        │  backend (FastAPI)   │        │  panel (React)  │
│  WordPress      │        │                      │        │  dashboard      │
│                 │        │  ┌────────────────┐  │        │  operatori      │
│ • widget chat   │──chat──▶│  │ RAG + LLM      │  │◀──API──│                 │
│ • sync contenuti│─ingest─▶│  │ (LiteLLM)      │  │        │ • conversazioni │
│ • impostazioni  │        │  └────────────────┘  │        │ • ticket        │
└─────────────────┘        │  ┌────────────────┐  │        │ • knowledge base│
                           │  │ Postgres +     │  │        │ • statistiche   │
                           │  │ pgvector       │  │        └─────────────────┘
                           │  └────────────────┘  │
                           └──────────────────────┘
```

| Componente | Path | Stack | Ruolo |
|-----------|------|-------|-------|
| **Backend** | `backend/` | FastAPI, SQLModel, Postgres + pgvector, LiteLLM | API RAG, chat, ticketing, ingest |
| **Panel** | `panel/` | React 18, Vite | Dashboard operatori (conversazioni, ticket, upload KB, stats) |
| **Plugin WP** | `wp-plugin/` | PHP (WordPress), JS/CSS vanilla | Widget di chat + sincronizzazione automatica dei contenuti |
| **SDK browser** | `sdk/browser/` | JavaScript ESM | Client headless per siti non WordPress, sessione e API visitatore ([guida](docs/browser-sdk.md)) |
| **Sito marketing** | `website/` | HTML/CSS statico (zero build) | Landing promozionale: feature, prezzi, login/registrazione |
| **Adapter canali** | `cloudflare/` | Cloudflare Workers | Normalizzazione email, WhatsApp e canali Meta, verifica webhook e isolamento delle credenziali provider |

## Come funziona

1. **Ingest** — Il plugin WP invia al backend i contenuti pubblicati (pagine, articoli,
   prodotti WooCommerce) e le info generali del sito. Documenti (PDF, immagini con OCR, testo)
   possono essere caricati anche dal panel. L'ingest è **asincrono**: l'endpoint accoda un job
   (`IngestJob`) e risponde subito; un worker in background divide in chunk, calcola gli
   embedding e li salva in pgvector. Lo stato si verifica su `/ingest/jobs/{id}`.
2. **Chat** — Il widget invia il messaggio del visitatore a `/chat`. Il backend recupera i
   chunk più rilevanti (cosine distance), costruisce un prompt "rispondi solo dal contesto"
   e interroga l'LLM. I prodotti WooCommerce pertinenti vengono restituiti come card.
3. **Escalation** — Se la risposta non è nel contesto o serve autorità umana, la
   conversazione passa a `escalated` e viene creato un **ticket**. Due meccanismi:
   keyword deterministiche (rimborso, reclamo, elimina account…) + decisione dell'LLM
   (marker testuale `ESCALATE:`, più affidabile del tool-calling nativo sui modelli locali).
4. **Instradamento e SLA** — Nel momento dell'escalation la conversazione entra nel flusso
   help desk: se il tenant ha attivato l'instradamento automatico viene assegnata a turno agli
   operatori del reparto (round-robin), altrimenti resta nella coda non assegnata. Contestualmente
   parte l'orologio SLA sulla regola più specifica (reparto + priorità), con due scadenze —
   **prima risposta** e **risoluzione** — mostrate nell'inbox come `ok`, `in scadenza` o `violato`.
5. **Risposta operatore** — L'operatore risponde dal panel; il messaggio torna nella
   conversazione, che rientra in stato `open` e ferma la scadenza di prima risposta. Il widget fa
   polling per riceverlo. La chiusura della conversazione ferma la scadenza di risoluzione.

## Help desk: assegnazione, reparti e SLA

- **Reparti** — code di supporto del tenant (Vendite, Ordini, Resi…). Gli operatori assegnati a
  un reparto formano il turno usato dall'instradamento automatico; un reparto senza operatori
  non è un vicolo cieco: le conversazioni restano nella sua coda, non assegnate.
- **Priorità** — `low | normal | high | urgent`, impostabile dall'inbox e usata per scegliere la
  regola SLA.
- **Regole SLA** — minuti per la prima risposta e per la risoluzione, opzionalmente ristretti a un
  reparto e/o a una priorità. Vince la regola più specifica; `0` minuti disattiva quella scadenza.
  Cambiando priorità o reparto le scadenze vengono ricalcolate dall'istante di partenza originale.
- **Violazioni** — un monitor in background segna le scadenze superate una sola volta per
  conversazione e target, incrementa `wpai_sla_breaches_total{target=...}`, scrive nell'audit log e
  invia la notifica al webhook operatori (`OPERATOR_WEBHOOK_URL`).
- **Visibilità** — l'inbox mostra un badge per conversazione ed è filtrabile per stato SLA;
  `/stats` espone conversazioni tracciate, a rischio, violate, percentuale di rispetto e tempo
  medio di prima risposta.
- **CSAT** — quando l'operatore chiude la conversazione il widget chiede al visitatore un voto
  da 1 a 5 con commento facoltativo, una sola volta per conversazione. È una misura diversa dal
  👍/👎 sulla singola risposta AI: il report `/csat` incrocia voto medio, distribuzione, chi ha
  risolto (AI o operatore), operatore, reparto e periodo.
- **Tag e classificazione** — tag manuali tenant-scoped associabili a più conversazioni e
  filtrabili nell'inbox. La classificazione AI (intento, argomento, urgenza) parte in background
  dopo un'escalation, oppure su richiesta dal panel; è **solo consultiva**: non tocca stato,
  priorità, assegnazione o SLA. Il vocabolario è chiuso e ogni risposta fuori vocabolario,
  illeggibile o mancante lascia la conversazione senza classificazione, mai etichettata a caso.
- **Collaborazione** — note interne visibili solo al team (mai restituite agli endpoint del
  visitatore), menzioni `@nome` con elenco delle citazioni non lette, indicatore di presenza sulla
  conversazione che avvisa quando un collega sta già scrivendo, e registro delle azioni
  (`/conversations/{id}/activity`) alimentato dall'audit log del tenant.
- **Multilingua** — la lingua del visitatore viene rilevata a **ogni messaggio** con un
  riconoscitore deterministico (parole funzionali, nessuna chiamata AI in più sul percorso
  della chat) e il locale del browser resta solo un suggerimento: se il testo dice qualcosa,
  vince il testo. L'assistente risponde in quella lingua **anche quando la knowledge base è in
  un'altra**: gli embedding `bge-m3` sono multilingua, quindi il retrieval non viene mai
  filtrato per lingua e un contenuto italiano può rispondere a una domanda in tedesco. Le
  risposte deterministiche (carrello, ordini, fuori ambito) sono tradotte a template, non
  rigenerate: un dato d'ordine non deve poter cambiare passando da una lingua all'altra.
  Il widget ha un catalogo di testi separato (`chat-i18n.js`) e l'inbox filtra per lingua.
  Lingue supportate: italiano, inglese, spagnolo, francese, tedesco, portoghese.
- **Analytics avanzate e gap della knowledge base** — oltre ai contatori, le metriche di esito
  sul periodo: **deflection** (conversazioni chiuse senza che un umano intervenga), escalation,
  tempi di prima risposta e risoluzione in media e mediana, trend giornaliero. Il rilevamento
  dei gap deriva dai log AI a ogni interrogazione — nessuna tabella di lacune da mantenere
  allineata: una domanda sparisce dall'elenco appena il contenuto esiste. Conta come lacuna
  solo ciò che dipende davvero dalla knowledge base (l'AI ha deciso di non poter rispondere e
  non aveva contesto vicino, oppure il visitatore ha bocciato la risposta): un'escalation per
  parola chiave o un provider AI giù non c'entrano. Dal panel si risponde una volta
  («Insegna») e la domanda esce dall'elenco.
- **Lead capture e qualificazione** — form brevi configurabili (testo, email, telefono, scelta)
  mostrati dal widget all'escalation o all'avvio della chat, con testo di consenso registrato
  insieme al lead. Il punteggio è la somma dei punti dei campi effettivamente compilati — nessun
  peso nascosto, e i pesi non vengono mai inviati al browser. Elenco filtrabile nel panel,
  export CSV (con neutralizzazione delle formule) ed evento `lead.captured` per il CRM.
- **Messaggi proattivi** — il widget può proporre un messaggio prima che il visitatore scriva,
  con quattro trigger: pagina specifica (URL), tempo sulla pagina, intento di uscita e carrello
  pieno. Le regole vengono valutate nel browser (nessuna chiamata per pagina) e il visitatore
  comanda: al massimo un messaggio per pagina, mai a chat aperta o su una conversazione già
  avviata, frequenza configurabile (sessione/giorno/sempre) e «Non mostrare più» permanente.
  Impression e chat aperte sono contate per capire se una regola vale la pena.
- **Automazioni no-code** — regole «quando succede X, se vale Y, fai Z» configurabili dal panel:
  trigger sugli eventi della conversazione (creazione, escalation, risposta, chiusura,
  valutazione, classificazione AI, violazione SLA), condizioni su stato/priorità/reparto/
  assegnatario/intento/urgenza/tag/voto CSAT, e azioni su priorità, reparto, assegnazione
  (anche a turno), tag, chiusura, escalation, email e webhook. Il vocabolario è chiuso e
  validato al salvataggio — una regola incomprensibile viene rifiutata subito, non applicata a
  metà — e ogni valutazione finisce nel log delle esecuzioni, anche quando le condizioni non
  sono soddisfatte. Le azioni che generano nuovi eventi non possono innescare cascate infinite.
- **Viste salvate** — ogni operatore può salvare la combinazione corrente di filtri e
  ordinamento con un nome (es. «Urgenti non assegnate») e riaprirla con un clic. Una vista può
  essere personale o condivisa con il tenant; in entrambi i casi solo chi l'ha creata può
  rinominarla, condividerla o eliminarla. Gli ordinamenti disponibili sono per data, priorità e
  scadenza SLA più vicina.

## Modello dati

- **Client** — tenant, identificato da `api_key`.
- **Chunk** — pezzo di contenuto embeddato (documento o pagina sito).
- **Product** — prodotto WooCommerce strutturato (per renderizzare card nel widget).
- **Contact** — identità tenant-scoped condivisa tra conversazioni e canali; usa il browser id
  sul web e l'identificatore del provider per email e futuri canali.
- **Conversation** — `open | escalated | closed`, con lingua rilevata, priorità, operatore
  assegnato, reparto, canale/thread e scadenze SLA; l'accesso del widget alla singola conversazione richiede un token visitatore
  casuale distinto dalla `api_key`.
- **Message** — `user | assistant | operator`; per i canali esterni conserva anche l'id del
  provider, così i retry dei webhook restano idempotenti.
- **Ticket** — `open | answered | closed`, collegato a una conversazione.
- **Operator** — agente umano che accede al panel; appartiene a un client (password hashed).
- **OperatorSession** — token di sessione opaco emesso al login, eliminato al logout.
- **Department / DepartmentMember** — code di supporto del tenant e operatori che le presidiano
  (il turno usato dall'instradamento automatico).
- **SlaPolicy** — scadenze di prima risposta e risoluzione, opzionalmente ristrette a un reparto
  e/o a una priorità; vince la regola più specifica.
- **RoutingSetting** — modalità di assegnazione automatica del tenant (`off | round_robin`),
  reparto predefinito e cursore del turno.
- **SavedView** — filtri dell'inbox salvati con nome e ordinamento; personali o condivisi con il
  tenant, modificabili solo da chi li ha creati.
- **InternalNote / NoteMention** — note visibili solo agli operatori e colleghi citati al loro
  interno, con lo stato di lettura della menzione.
- **Tag / ConversationTag** — etichette del tenant (manuali o generate dalla classificazione AI)
  e loro associazione multipla alle conversazioni.
- **KnowledgeGapReview** — decisione dell'operatore su una lacuna rilevata (risposta insegnata
  o ignorata); le lacune in sé sono derivate, non memorizzate.
- **LeadForm / Lead** — form di qualificazione del tenant (campi, punti, consenso) e lead
  raccolti, ciascuno con lo snapshot del consenso accettato.
- **ProactiveRule** — messaggio contestuale del widget con trigger, filtro URL, frequenza e
  contatori di visualizzazioni/chat aperte.
- **Workflow / WorkflowRun** — regole di automazione del tenant (trigger, condizioni e azioni
  come JSON validato) e registro di ogni valutazione, con le azioni effettivamente applicate.
- **ApiKey** — credenziale server-to-server dell'API pubblica: scoped, revocabile, salvata come
  digest (distinta dalla `api_key` pubblica del widget).
- **WebhookEndpoint / WebhookDelivery** — destinazioni firmate del tenant e log/coda delle
  consegne con i tentativi.
- **ConversationRating** — CSAT: voto 1–5 (con commento facoltativo) lasciato dal visitatore
  sull'intera conversazione, distinto dal feedback 👍/👎 sulla singola risposta AI.

### Due tipi di credenziale

- **api_key del client** — machine-to-machine: usata da widget e plugin WP per `/chat` e ingest.
- **Token operatore** — sessione umana a scadenza: ottenuto via login email+password,
  usato dal panel.

La `api_key` inclusa nel widget identifica il tenant ma non è considerata segreta. Alla
creazione della chat il backend restituisce un `conversation_token` ad alta entropia; il
browser deve presentarlo per continuare o leggere quella conversazione. Nel database viene
salvato soltanto il suo hash.

L'endpoint `/conversations/{id}/messages` accetta entrambi (il widget lo interroga in polling,
il panel lo legge).

## Quick start (sviluppo)

### Backend

```bash
cd backend
cp .env.example .env            # personalizza modelli / DB se serve
docker compose up -d            # Postgres+pgvector e Ollama
# scarica i modelli nel container ollama (default: llama3.1 + nomic-embed-text)
docker compose exec ollama ollama pull llama3.1
docker compose exec ollama ollama pull nomic-embed-text

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
alembic upgrade head             # crea/aggiorna lo schema del DB
uvicorn app.main:app --reload   # http://localhost:8000
```

> **Creare client e operatori:** più comodo dal **pannello superadmin** (`/#admin` nel panel,
> vedi sotto) — form per creare client, impostare origin CORS, rigenerare l'api_key, e
> aggiungere/rimuovere operatori. In alternativa, via API diretta:
> ```bash
> curl -X POST http://localhost:8000/admin/clients \
>   -H "Authorization: Bearer $ADMIN_API_KEY" \
>   -H "Content-Type: application/json" \
>   -d '{"name": "Acme Srl"}'
> # -> {"id": 1, "name": "Acme Srl", "api_key": "…"}  ← salva l'api_key, è mostrata solo qui
> curl -X POST http://localhost:8000/admin/clients/1/operators \
>   -H "Authorization: Bearer $ADMIN_API_KEY" \
>   -H "Content-Type: application/json" \
>   -d '{"email": "op@acme.it", "password": "…"}'
> ```

### Test (backend)

```bash
cd backend
pip install -r requirements-dev.lock
pytest                              # test unitari (security, rate limit, LLM, chunking)

# test d'integrazione degli endpoint (richiedono un DB Postgres+pgvector di test):
TEST_DATABASE_URL=postgresql+psycopg://rag:rag@localhost:5432/rag_test pytest
```
Senza `TEST_DATABASE_URL` i test d'integrazione vengono saltati; l'LLM è mockato, quindi non
serve Ollama.

### Panel

```bash
cd panel
npm install
npm run dev                     # http://localhost:5173
```
Il panel ha un **tema chiaro/scuro/automatico**, con il selettore in fondo alla barra laterale
(sia operatore sia superadmin). La preferenza vive nel browser (`localStorage`), non nell'account:
appartiene allo schermo che stai usando. Su «automatico» segue il sistema operativo e reagisce
dal vivo se cambia. Il tema viene applicato da uno script inline in `index.html` prima del primo
frame, altrimenti chi usa il tema scuro vedrebbe un lampo bianco a ogni caricamento.

Configura il backend con `VITE_API_BASE` (default `http://localhost:8000`). All'avvio
accedi con **email e password dell'operatore** (crealo prima via endpoint admin, vedi sopra).

**Pannello superadmin**: `/#admin` (identità separata dal login operatore — mai lo stesso
storage/token). Accesso con `ADMIN_API_KEY` come "password" — tenuta in `sessionStorage`,
non `localStorage`, così non resta su disco oltre la chiusura della scheda. Da lì: creare
client, vedere conteggi d'uso (conversazioni/operatori/chunk/prodotti) per client, gestire
origin CORS, rigenerare api_key, aggiungere/rimuovere operatori, lanciare un re-embed globale,
gestire i **piani** (prezzo, limiti chat/ingest) e assegnarli ai client. Più le viste di
osservabilità: **Panoramica** (statistiche globali: volume, % risolte da AI, latenza, top
client), **Problematiche** (turni AI da rivedere → apri il debug), **Debug conversazione**
(per ogni turno: contesto recuperato con distanze e selezione, modello, latenza, token),
**Log azioni** (audit) e **Sistema** (stato DB, coda ingest, migrazione, modelli, versione).

#### Billing

Il billing è **integrato end-to-end con Stripe**. Fondamenta: modello `Plan` (nome, prezzo,
limiti rate-limit per chat/ingest), ogni `Client` è legato a un piano (default "Free", seedato
dalla migrazione `0005`) e i rate limit su `/chat` e `/ingest/*` derivano dal piano del client.
Le fondamenta funzionano anche senza chiavi Stripe; per attivare pagamenti e self-service serve
un account Stripe (anche solo di *test*) — setup in [`deploy/STRIPE.md`](deploy/STRIPE.md).

Con Stripe configurato (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, e lo `stripe_price_id` sui
piani a pagamento):
- **Registrazione self-service** (`POST /signup`): crea account + operatore e apre una Stripe
  Checkout subscription con prova gratuita (`TRIAL_DAYS`) e cattura carta. Se SMTP è configurato,
  il nuovo operatore **verifica l'email** prima di poter accedere (vedi sopra, email transazionali);
  senza SMTP la verifica è disattivata e l'account è subito utilizzabile (niente link non recapitabili).
- **Checkout upgrade** dal panel (`POST /billing/checkout`) per cambiare piano.
- **Portale di fatturazione** (`POST /billing/portal`): apre il portale ospitato da Stripe dove il
  cliente aggiorna il metodo di pagamento, scarica le fatture, cambia piano e disdice da solo.
  Nessun dato di carta transita da noi; le modifiche rientrano come webhook. Senza un
  `stripe_customer_id` (tenant che non ha mai fatto checkout) risponde `409`.
- **Webhook** (`POST /billing/webhook`, firma verificata): sincronizza
  `plan_id`/`billing_status`/`stripe_customer_id`/`stripe_subscription_id` sugli eventi
  `checkout.session.completed` e `customer.subscription.created/updated/deleted`, e specchia
  `subscription_period_end`/`subscription_cancel_at_period_end` sul client, così `/usage` — che il
  plugin WordPress interroga — non chiama mai Stripe in linea.
- **Avvisi al cliente**: su `invoice.payment_failed`, `customer.subscription.trial_will_end`,
  disdetta programmata e `customer.subscription.deleted` vengono inviate email agli operatori
  verificati del tenant. Un errore di invio non blocca la sincronizzazione (Stripe riceve `200`).
- **Enforcement**: su `canceled` il client torna automaticamente al piano Free (i limiti per-piano
  seguono); `past_due` mantiene il piano come periodo di grazia mentre Stripe ritenta.
- **Costi e margine per tenant** (`GET /admin/costs?days=30`, listino su `/admin/model-prices`):
  il costo AI di ogni cliente è calcolato dai token già registrati in `AiResponseLog`, usando un
  listino per modello gestito dal superadmin. Il prezzo si inserisce **per milione di token nella
  valuta del provider, come pubblicato** (es. `0.152`): internamente è un intero in millesimi di
  centesimo, così `$0,012/M` non viene arrotondato a un centesimo. Un modello senza prezzo **non
  vale zero**: finisce in `unpriced_models` ed è escluso dai totali, così il numero appare
  incompleto e non piccolo. Se listino e piani usano **valute diverse** gli importi non vengono
  convertiti: la risposta segnala `mixed_currencies` e omette la percentuale di margine.
  Il calcolo comprende **inferenza, embedding e storage**: gli embedding sono contati sia
  sull'ingest sia su ogni domanda in chat (rollup giornaliero in `EmbeddingUsage`), e lo storage
  è la somma degli allegati per tenant, già mensile e quindi non riscalato sulla finestra.
  Restano fuori email e canali, quindi il margine è ancora un tetto.
- **Attivazione e clienti a rischio** (`GET /admin/activation?days=90`, `GET /admin/at-risk?days=14`):
  il funnel conta gli account della coorte lungo cinque passi — creato, plugin collegato, prima
  conversazione, **prima risposta utile**, primo pagamento — con il tempo mediano fino
  all'attivazione e l'elenco di chi è rimasto bloccato. Una chat a cui l'AI non ha mai risposto
  non è un'attivazione. I clienti senza data di registrazione (creati prima della migrazione
  `0049`) sono esclusi dalla coorte e contati a parte, non conteggiati come mancate attivazioni.
  Il rischio è un **elenco di motivi** — insoluto, disdetta programmata, calo d'uso, silenzio,
  mai usato, CSAT basso — non un punteggio opaco, e il calo è misurato sul periodo precedente
  dello stesso cliente, non rispetto agli altri tenant.
- **Azioni commerciali del superadmin** (`/admin/clients/{id}/subscription/*`): proroga della
  prova contata da oggi, applicazione e rimozione di un coupon Stripe, sospensione e ripresa
  degli addebiti, disdetta e revoca della disdetta. Tutte agiscono **su Stripe** e non scrivono
  nulla nel database: è il webhook a farlo, quindi non esiste un istante in cui le due parti
  dicono cose diverse. La disdetta è sempre a fine periodo pagato, mai immediata. Anche
  `POST /admin/clients/{id}/plan` passa da Stripe quando il cliente ha un abbonamento —
  restituisce `pending_plan_id` finché il webhook non conferma — e resta una scrittura diretta
  solo per i clienti senza abbonamento.
- **Ricavi per il superadmin** (`GET /admin/revenue?days=30`): MRR/ARR, ricavo medio e clienti
  paganti, ripartizione per piano, insoluti, prove in scadenza e disdette (programmate e del
  periodo). Gli abbonamenti annuali sono normalizzati a un dodicesimo, quindi serve
  `subscription_interval` sul client: lo imposta il webhook. Le tre voci — incassato, a rischio,
  in prova — restano **separate**, e le disdette sono un **conteggio**, non un tasso: senza
  storico della base clienti un churn rate sarebbe inventato.

### Plugin WP

Per lo sviluppo: copia `wp-plugin/wp-aissistant/` direttamente in `wp-content/plugins/`
(o creane un symlink). Per un'installazione via upload WP standard, genera lo zip:

```bash
cd wp-plugin
./build.sh                      # -> dist/wp-aissistant-<versione>.zip
```

Lo script legge la versione dal docblock del plugin e fallisce se non combacia con la
costante `WPAI_VERSION` (tenerle allineate a mano ad ogni release, insieme a una voce in
`wp-plugin/wp-aissistant/CHANGELOG.md`). La CI builda lo zip ad ogni push come artifact
(`plugin-build` job).

Dopo l'installazione, attiva il plugin e in **Impostazioni → WP AIssistant** imposta
Backend URL e API Key. Usa "Sincronizza ora" per il primo caricamento della knowledge base.

Per un pacchetto distribuibile (`.zip` installabile da *Plugin → Aggiungi nuovo → Carica*):

```bash
bash wp-plugin/build.sh          # -> wp-plugin/dist/wp-aissistant-<versione>.zip
```
La versione è letta dall'header del plugin; il changelog è in `wp-plugin/wp-aissistant/readme.txt`
(formato WordPress). La CI produce lo zip come artifact a ogni push/PR.

## Deploy (Docker)

Il backend è containerizzato. Il modo più rapido per avviare tutto lo stack (Postgres+pgvector,
Ollama e backend) è `docker compose`:

```bash
cd backend
ADMIN_API_KEY=<un-token-sicuro> docker compose up --build
# il backend applica le migrazioni (alembic upgrade head) e parte su http://localhost:8000
# poi scarica i modelli nel container ollama:
docker compose exec ollama ollama pull llama3.1
docker compose exec ollama ollama pull nomic-embed-text
```

Il servizio `backend` attende che il DB sia healthy, esegue le migrazioni e serve l'app; espone
un `GET /health` per gli healthcheck del container/orchestratore. Panel e sito marketing sono
asset statici: buildali (`npm run build` per il panel) e servili con qualsiasi web server / CDN.

In produzione metti un **reverse proxy con TLS** davanti al backend (non esporre la 8000
pubblicamente): esempi pronti per Caddy (HTTPS automatico) e Nginx, più la guida completa
(real client IP dietro proxy, `/metrics` non pubblico, CORS), in **[`deploy/`](deploy/)**.

Immagine backend pubblicata su **GHCR** a ogni CI verde su `main`:

```bash
docker pull ghcr.io/andreaem-it/wp-aissistant-backend:latest
# oppure un commit specifico: ...:sha-<commit>
```

Per la **produzione con un comando** c'è [`docker-compose.prod.yml`](docker-compose.prod.yml)
(backend da GHCR, Caddy con HTTPS automatico davanti, backend non esposto, CORS ristretto):

```bash
export ADMIN_API_KEY=<token-robusto> POSTGRES_PASSWORD=<password>
# edita deploy/Caddyfile con il tuo dominio, poi:
docker compose -f docker-compose.prod.yml up -d
```
(Il pacchetto GHCR nasce privato: rendilo pubblico dalle *Package settings* se vuoi pull senza login.)

## API pubblica e webhook

Per collegare CRM e automazioni ci sono due strade complementari, documentate in
[`docs/public-api.md`](docs/public-api.md):

- **API `/v1` versionata** — chiavi con permessi limitati (`conversations:read`,
  `conversations:write`, `knowledge:write`, `stats:read`), mostrate una sola volta e revocabili,
  con rate limit dedicato. Espone elenco/dettaglio conversazioni, risposta, cambio stato, tag,
  statistiche e ingest di documenti. Le note interne non fanno parte del contratto pubblico.
- **Webhook firmati** — eventi `conversation.created|message.received|escalated|replied|closed|rated` e
  `sla.breached` recapitati sull'endpoint HTTPS del tenant con `X-WPAI-Signature`
  (HMAC-SHA256 su `timestamp.corpo`), riprovi con backoff esponenziale fino a 5 tentativi e log
  delle consegne consultabile dal panel. Gli URL interni/privati sono rifiutati (protezione
  SSRF) sia alla creazione sia prima di ogni consegna.

## Configurazione (backend/.env)

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://rag:rag@localhost:5432/rag` | Connessione Postgres |
| `EMBED_DIM` | `1024` | Dimensione embedding — deve combaciare con `EMBED_MODEL` (1024 = bge-m3, 768 = nomic) |
| `DB_AUTO_CREATE` | `false` | `true` crea le tabelle dai modelli allo startup (solo dev; in prod usa Alembic) |
| `CHAT_MODEL` | `ollama/llama3.1` | Modello chat (formato LiteLLM) |
| `EMBED_MODEL` | `ollama/nomic-embed-text` | Modello embedding |
| `LLM_API_BASE` | `http://localhost:11434` | Endpoint LLM (Ollama locale) |
| `ADMIN_API_KEY` | *(non impostato)* | Token per gli endpoint `/admin/clients`; se assente l'admin API è disabilitata |
| `CHAT_RATE_LIMIT` | `30` | Richieste `/chat` per 60s, per client+IP |
| `INGEST_RATE_LIMIT` | `60` | Richieste di ingest per 60s, per client |
| `REDIS_URL` | *(non impostato)* | Store condiviso per il rate limiter (necessario in multi-worker); se assente usa l'in-memory per-processo. Fail-open se Redis è irraggiungibile |
| `PANEL_ORIGINS` | `http://localhost:5173` | Origin del panel ammessi dal CORS (comma-separated) |
| `CORS_ALLOW_ALL` | `true` | `true` riflette qualsiasi Origin; `false` applica l'allowlist |
| `STRICT_PRODUCTION_CONFIG` | `false` | Se `true`, impedisce l'avvio con secret deboli, CORS aperto o dipendenze production mancanti |
| `INGEST_WORKER_ENABLED` | `true` | Avvia il worker di ingest nel processo dell'app (coda condivisa via Postgres) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | *(non impostati)* | Abilitano `/billing/*`; se assenti il billing è disattivato — setup in [`deploy/STRIPE.md`](deploy/STRIPE.md) |
| `EMBEDDING_CHARS_PER_TOKEN` | `4` | Caratteri per token usati a **stimare** i token di embedding quando il provider non li riporta (Cloudflare restituisce solo il vettore); il costo derivato è segnalato come stima |
| `STORAGE_PRICE_PER_GB_MONTH_MILLICENTS` | *(non impostato)* | Prezzo dello storage allegati in millesimi di centesimo per GB-mese. Senza, lo storage è **non prezzato** — escluso dal totale e segnalato, mai contato come gratis |
| `BILLING_PORTAL_RETURN_URL` | *(usa `BILLING_SUCCESS_URL`)* | Dove Stripe riporta il cliente quando chiude il portale di fatturazione |
| `DOCS_ENABLED` | `false` | Espone `/docs`, `/redoc`, `/openapi.json` (off di default in prod) |
| `METRICS_TOKEN` | *(non impostato)* | Se assente `/metrics` è disabilitato; se impostato richiede `Bearer <token>` |
| `EMAIL_PROVIDER` | `smtp` | `smtp` o `brevo_api`. Usa `brevo_api` (invio via HTTPS) su host che bloccano le porte SMTP in uscita (es. Railway) |
| `BREVO_API_KEY` | *(non impostato)* | Chiave API v3 di Brevo (richiesta con `EMAIL_PROVIDER=brevo_api`) |
| `EMAIL_FROM_NAME` | `WP AIssistant` | Nome mittente mostrato nelle email |
| `SMTP_HOST` | *(non impostato)* | Host SMTP per le email transazionali (verifica email, reset password). Se assente (e provider `smtp`) le email vengono solo loggate (dev) |
| `SMTP_PORT` | `587` | Porta SMTP |
| `SMTP_USER` / `SMTP_PASSWORD` | *(non impostati)* | Credenziali SMTP |
| `SMTP_FROM` | *(= `SMTP_USER`)* | Indirizzo mittente |
| `SUPPORT_EMAIL_ADDRESS` | `support@wpaissistant.it` | Reply-To delle conversazioni email, instradato al Worker inbound |
| `WHATSAPP_OUTBOUND_URL` | *(non impostato)* | Endpoint HTTPS dell'adapter WhatsApp tenant-aware per le risposte operatore |
| `WHATSAPP_OUTBOUND_TOKEN` | *(non impostato)* | Bearer token condiviso con l'adapter WhatsApp; le credenziali Meta non entrano nel database |
| `WHATSAPP_OUTBOUND_TIMEOUT` | `10` | Timeout dell'adapter WhatsApp in secondi |
| `META_MESSAGING_OUTBOUND_URL` | *(non impostato)* | Endpoint HTTPS dell'adapter tenant-aware per Messenger e Instagram Direct |
| `META_MESSAGING_OUTBOUND_TOKEN` | *(non impostato)* | Bearer token condiviso con l'adapter Meta; le credenziali Graph API restano nell'adapter |
| `META_MESSAGING_OUTBOUND_TIMEOUT` | `10` | Timeout dell'adapter Messenger/Instagram in secondi |
| `CRM_ADAPTER_URL` | *(non impostato)* | Endpoint HTTPS dell'adapter tenant-aware per sincronizzare lead con Brevo/Zoho/Pipedrive ([guida](docs/crm-integrations.md)) |
| `CRM_ADAPTER_TOKEN` | *(non impostato)* | Bearer token backend→adapter CRM; le credenziali OAuth dei provider restano nell'adapter |
| `CRM_ADAPTER_TIMEOUT` | `10` | Timeout dell'adapter CRM in secondi |
| `HELPDESK_ADAPTER_URL` | *(non impostato)* | Endpoint HTTPS dell’adapter tenant-aware per l’handoff Zendesk/Freshdesk ([guida](docs/helpdesk-integrations.md)) |
| `HELPDESK_ADAPTER_TOKEN` | *(non impostato)* | Bearer token backend→adapter helpdesk; le credenziali provider restano nell’adapter |
| `HELPDESK_ADAPTER_TIMEOUT` | `10` | Timeout dell’adapter helpdesk in secondi |
| `ATTACHMENT_STORAGE_URL` | *(non impostato)* | URL del Worker Cloudflare autenticato che media l’accesso al bucket R2 privato |
| `ATTACHMENT_STORAGE_TOKEN` | *(non impostato)* | Bearer token condiviso backend→Worker; non viene mai inviato al browser |
| `ATTACHMENT_STORAGE_TIMEOUT` | `15` | Timeout upload/download/cancellazione in secondi |
| `ATTACHMENT_MAX_BYTES` | `10485760` | Dimensione massima di un allegato operatore (10 MB di default) |
| `VAPID_PUBLIC_KEY` | *(non impostato)* | Chiave pubblica URL-safe per sottoscrivere i browser alle notifiche push |
| `VAPID_PRIVATE_KEY` | *(non impostato)* | Chiave privata VAPID, conservata soltanto nel backend |
| `VAPID_SUBJECT` | `mailto:support@wpaissistant.it` | Contatto del mittente Web Push (`mailto:` o URL HTTPS) |
| `SMTP_TLS` | `true` | `true` = STARTTLS, `ssl` = SMTPS, `false` = nessuna cifratura |
| `PANEL_PUBLIC_URL` | *(= primo `PANEL_ORIGINS`)* | URL pubblico del panel, usato per costruire i link nelle email (`/?verify=`, `/?reset=`) |
| `VERIFY_TOKEN_TTL_HOURS` | `48` | Validità del link di verifica email |
| `RESET_TOKEN_TTL_HOURS` | `1` | Validità del link di reset password |
| `SLA_MONITOR_ENABLED` | `true` | Avvia il monitor che segnala le scadenze SLA superate (alert + metriche) |
| `SLA_CHECK_INTERVAL_SECONDS` | `300` | Intervallo tra due controlli SLA |
| `SLA_WARN_RATIO` | `0.8` | Quota della finestra dopo cui una scadenza passa a `in_scadenza` |
| `PRESENCE_TTL_SECONDS` | `20` | Durata di un battito di presenza operatore su una conversazione |
| `MAX_NOTE_CHARS` | `4000` | Lunghezza massima di una nota interna |
| `MAX_RATING_COMMENT_CHARS` | `1000` | Lunghezza massima del commento CSAT |
| `PUBLIC_API_RATE_LIMIT` | `120` | Richieste `/v1` per 60s, per chiave API |
| `WEBHOOK_DISPATCHER_ENABLED` | `true` | Avvia il dispatcher che consegna e ritenta i webhook |
| `WEBHOOK_DISPATCH_INTERVAL_SECONDS` | `15` | Intervallo tra due giri di consegna |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | Tentativi massimi per consegna prima di marcarla fallita |
| `WEBHOOK_TIMEOUT_SECONDS` | `5` | Timeout della singola consegna |
| `WEBHOOK_ALLOW_PRIVATE` | `false` | `true` consente URL locali/privati (solo sviluppo e test) |
| `AI_CLASSIFY_ENABLED` | `true` | Classificazione AI automatica della conversazione dopo un'escalation |
| `MAX_TAGS_PER_CLIENT` | `200` | Tetto ai tag distinti per tenant (la classificazione riusa quelli esistenti) |
| `CLASSIFY_MAX_MESSAGES` / `CLASSIFY_MAX_CHARS` | `12` / `4000` | Quanta conversazione viene inviata al classificatore |
| `RETRIEVE_FETCH_K` | `20` | Pool di candidati recuperati prima del rerank MMR |
| `MMR_LAMBDA` | `0.5` | Bilanciamento MMR: `1.0` = solo rilevanza, `0.0` = solo diversità |

LiteLLM permette di passare a OpenAI / Claude / **Cloudflare Workers AI** / altri provider
cambiando `CHAT_MODEL`, `EMBED_MODEL` e le relative credenziali, senza modifiche al codice.

**Cloudflare Workers AI** (inferenza edge, senza GPU da ospitare) — esempio in `.env.example`:
`CHAT_MODEL=cloudflare/@cf/meta/llama-3.1-8b-instruct`, `EMBED_MODEL=cloudflare/@cf/baai/bge-m3`
(1024-dim → `EMBED_DIM=1024`) + `CLOUDFLARE_API_KEY`/`CLOUDFLARE_ACCOUNT_ID`. Cambiare modello di
embedding richiede la migrazione `0004` e un re-embed dei contenuti via `POST /admin/reembed`
(la ricerca ignora i chunk non ancora ri-embeddati nel frattempo).

## API principali (backend)

Auth via header `Authorization: Bearer <token>`. La colonna *Auth* indica quale credenziale:
🔑 api_key client · 👤 token operatore · 🔀 entrambi · 🛡️ `ADMIN_API_KEY` ·
🔓 chiave dell'API pubblica con lo scope indicato (vedi [`docs/public-api.md`](docs/public-api.md)).

| Endpoint | Metodo | Auth | Descrizione |
|----------|--------|------|-------------|
| `/health` | GET | — | Liveness probe (nessuna auth) |
| `/metrics` | GET | 🔒 | Metriche Prometheus — disabilitato se `METRICS_TOKEN` non è impostato; altrimenti `Bearer <METRICS_TOKEN>` |
| `/chat` | POST | 🔑 | Messaggio visitatore → risposta o escalation (ritorna `message_id`) |
| `/chat/stream` | POST | 🔑 | Come `/chat` ma in streaming SSE (token progressivi); il widget lo usa con fallback su `/chat` |
| `/chat/feedback` | POST | 🔑 | Valutazione 👍/👎 su una risposta AI (scoping per conversazione) |
| `/chat/rating` | POST | 🔑 | CSAT del visitatore sull'intera conversazione (voto 1–5 + commento); reinviarlo aggiorna il precedente |
| `/analytics/overview` | GET | 👤 | Deflection, escalation, tempi di prima risposta/risoluzione (media e mediana) e trend giornaliero |
| `/analytics/knowledge-gaps` | GET | 👤 | Domande senza risposta utile, raggruppate e ordinate per frequenza, con i temi aperti |
| `/analytics/knowledge-gaps/review` | POST | 👤 | Segna una lacuna come risolta o ignorata |
| `/widget/lead-form` | GET | 🔑 | Form di qualificazione attivo per il momento indicato (senza i pesi del punteggio) |
| `/widget/leads` | POST | 🔑 | Invio del form da parte del visitatore (consenso verificato lato server) |
| `/lead-forms` | GET/POST | 👤 | Form di qualificazione del tenant |
| `/lead-forms/{id}` | PATCH/DELETE | 👤 | Aggiorna o elimina un form (i lead raccolti restano) |
| `/leads` | GET | 👤 | Lead raccolti, filtrabili per punteggio minimo e periodo |
| `/leads/export` | GET | 👤 | Export CSV dei lead (una colonna per campo, formule neutralizzate) |
| `/crm/connections` | GET | 👤 | Collegamenti CRM del tenant e provider supportati |
| `/crm/connections/{provider}` | PUT/DELETE | 👤 | Collega, aggiorna o scollega Brevo/Zoho/Pipedrive |
| `/leads/{id}/crm-sync` | POST | 👤 | Invia esplicitamente un lead al CRM collegato e registra l’esito |
| `/helpdesk/connections` | GET | 👤 | Collegamenti helpdesk Zendesk/Freshdesk del tenant |
| `/helpdesk/connections/{provider}` | PUT/DELETE | 👤 | Configura o rimuove una destinazione helpdesk |
| `/tickets/{id}/helpdesk-export` | POST | 👤 | Trasferisce contatto e transcript al provider configurato con retry idempotente |
| `/support-schedule` | GET/PUT | 👤 | Calendario lavorativo tenant-scoped usato per sospendere gli SLA fuori orario |
| `/plugin/register` | POST | 🔑 | Registra un’installazione WordPress dopo challenge HMAC sul dominio autorizzato |
| `/plugin/support-schedule` | PUT | 🔌 | Sincronizza orari e fuso con la credenziale privata dell’installazione |
| `/widget/proactive` | GET | 🔑 | Regole proattive attive per il widget (solo trigger e messaggio) |
| `/widget/proactive/{id}/event` | POST | 🔑 | Conta una visualizzazione o una chat aperta dal messaggio |
| `/proactive-rules` | GET/POST | 👤 | Messaggi proattivi del tenant, con i contatori di conversione |
| `/proactive-rules/{id}` | PATCH/DELETE | 👤 | Aggiorna o elimina un messaggio proattivo |
| `/workflows` | GET/POST | 👤 | Automazioni del tenant + vocabolario (trigger, campi, operatori, azioni) |
| `/workflows/{id}` | PATCH/DELETE | 👤 | Aggiorna o elimina una regola (con il suo storico) |
| `/workflows/{id}/preview` | POST | 👤 | Prova a secco su una conversazione reale: dice se scatterebbe e cosa farebbe, senza applicare nulla |
| `/workflows/{id}/runs` | GET | 👤 | Log delle esecuzioni (esito, azioni applicate, errori) |
| `/api-keys` | GET/POST | 👤 | Chiavi dell'API pubblica (la chiave in chiaro è restituita una sola volta) |
| `/api-keys/{id}` | DELETE | 👤 | Revoca una chiave |
| `/webhooks` | GET/POST | 👤 | Endpoint webhook del tenant ed eventi disponibili |
| `/webhooks/{id}` | PATCH/DELETE | 👤 | Aggiorna (URL, eventi, attivazione) o elimina un endpoint |
| `/webhooks/{id}/test` | POST | 👤 | Invia una consegna di prova firmata e riporta l'esito reale |
| `/webhooks/{id}/deliveries` | GET | 👤 | Log delle consegne (stato, tentativi, codice HTTP, errore) |
| `/channels/email/inbound` | POST | 🔓 | Adapter inbound email (scope `channels:write`), con deduplicazione e threading ([guida](docs/email-channel.md)) |
| `/channels/whatsapp/inbound` | POST | 🔓 | Adapter inbound WhatsApp (scope `channels:write`), consenso, deduplicazione e threading ([guida](docs/whatsapp-channel.md)) |
| `/channels/meta/inbound` | POST | 🔓 | Adapter inbound Messenger/Instagram (scope `channels:write`), deduplicazione, contatto e threading ([guida](docs/meta-messaging-channel.md)) |
| `/conversations/{id}/whatsapp/status` | GET | 🔒 | Stato finestra di 24 ore e consenso WhatsApp |
| `/conversations/{id}/whatsapp/template` | POST | 🔒 | Invio di un template WhatsApp approvato con consenso registrato |
| `/conversations/{id}/attachments` | POST | 🔒 | Carica un allegato operatore nel bucket R2 privato e crea il relativo messaggio solo dopo conferma storage |
| `/attachments/{id}` | GET/DELETE | 🔒 | Scarica o elimina un allegato con controllo tenant e risposta `private, no-store` |
| `/push/config` | GET | 🔒 | Configurazione e preferenze Web Push dell'operatore |
| `/push/subscriptions` | POST/DELETE | 🔒 | Attiva o disattiva un dispositivo dell'operatore |
| `/push/preferences` | PATCH | 🔒 | Preferenze per escalation, assegnazioni, menzioni e SLA |
| `/v1/conversations` | GET | 🔓 | API pubblica: elenco conversazioni (scope `conversations:read`) |
| `/v1/conversations/{id}` | GET | 🔓 | Dettaglio con messaggi (senza note interne) |
| `/v1/conversations/{id}/reply` | POST | 🔓 | Risposta dall'esterno (scope `conversations:write`) |
| `/v1/conversations/{id}/status` | POST | 🔓 | Chiude o riapre la conversazione |
| `/v1/conversations/{id}/tags` | POST | 🔓 | Applica un tag (creandolo se serve) |
| `/v1/stats` | GET | 🔓 | Statistiche del tenant (scope `stats:read`) |
| `/v1/knowledge/documents` | POST | 🔓 | Accoda un documento nella knowledge base (scope `knowledge:write`) |
| `/csat` | GET | 👤 | Report CSAT per periodo: media, distribuzione, AI vs operatore, per operatore, per reparto e ultimi commenti |
| `/chat/contact` | POST | 🔑 | Il visitatore lascia l'email (all'escalation) per essere notificato alla risposta operatore |
| `/ingest/site-page` | POST | 🔑 | Push contenuto pagina/articolo (dal plugin) |
| `/ingest/product` | POST | 🔑 | Push prodotto WooCommerce (dal plugin) |
| `/ingest/document` | POST | 👤 | Upload documento (PDF/immagine/testo) dal panel |
| `/ingest/jobs/{id}` | GET | 🔀 | Stato di un job di ingest (`queued`/`processing`/`done`/`error`) |
| `/conversations` | GET | 👤 | Lista conversazioni del client, filtrabile per stato, priorità, reparto, assegnazione e stato SLA (`sla_state=ok\|in_scadenza\|violato`) e ordinabile (`sort=recent\|oldest\|priority\|sla`); filtra anche per `tag_id`, `intent`, `urgency` e `conversation_language` |
| `/conversations/{id}/routing` | PATCH | 👤 | Imposta priorità, operatore assegnato e reparto della conversazione (ricalcola le scadenze SLA) |
| `/conversations/{id}/messages` | GET | 🔀 | Messaggi (polling widget + lettura panel) |
| `/tickets` | GET | 👤 | Ticket per stato |
| `/tickets/{id}/reply` | POST | 👤 | Risposta operatore (via ticket) |
| `/conversations/{id}/reply` | POST | 👤 | Risposta operatore diretta dalla conversazione (chiude eventuali ticket aperti, notifica il visitatore) |
| `/conversations/{id}/status` | POST | 👤 | Chiude (risolta/archiviata) o riapre una conversazione; un nuovo messaggio del visitatore la riapre da solo |
| `/conversations/{id}` | DELETE | 👤 | GDPR erasure: elimina conversazione + messaggi/ticket/log AI |
| `/gdpr/erase` | POST | 👤 | GDPR right-to-be-forgotten: elimina tutte le conversazioni con una data email visitatore |
| `/gdpr/export` | POST | 👤 | GDPR data portability: esporta profilo, conversazioni, messaggi e ticket associati a una email |
| `/stats` | GET | 👤 | Contatori conversazioni |
| `/usage` | GET | 🔑/👤 | Uso messaggi del mese vs quota del piano (usato/limite/rimanenti) — per plugin e panel |
| `/knowledge-base` | GET | 👤 | Documenti/pagine (raggruppati, con conteggio chunk) e prodotti sincronizzati |
| `/me` | GET | 👤 | Profilo operatore: email, nome client, api_key del widget |
| `/team/operators` | GET | 👤 | Operatori del tenant disponibili per l'assegnazione |
| `/departments` | GET/POST | 👤 | Elenca o crea reparti/code di supporto tenant-scoped |
| `/departments/{id}` | DELETE | 👤 | Elimina un reparto, i suoi membri e le regole SLA collegate; le conversazioni tornano nella coda generale |
| `/departments/{id}/members` | GET/POST | 👤 | Operatori del turno di un reparto |
| `/departments/{id}/members/{operator_id}` | DELETE | 👤 | Rimuove un operatore dal turno del reparto |
| `/sla-policies` | GET/POST | 👤 | Regole SLA del tenant (prima risposta, risoluzione, reparto, priorità) |
| `/sla-policies/{id}` | PATCH/DELETE | 👤 | Aggiorna o rimuove una regola SLA (le conversazioni in corso vengono riallineate) |
| `/routing-settings` | GET/PUT | 👤 | Instradamento automatico: `off` o `round_robin`, con reparto predefinito |
| `/tags` | GET/POST | 👤 | Tag del tenant (nome + colore) |
| `/tags/{id}` | DELETE | 👤 | Elimina un tag e lo stacca da tutte le conversazioni |
| `/conversations/{id}/tags` | POST | 👤 | Applica un tag esistente (`tag_id`) o creane uno per nome |
| `/conversations/{id}/tags/{tag_id}` | DELETE | 👤 | Rimuove un tag dalla conversazione |
| `/conversations/{id}/classify` | POST | 👤 | Classificazione AI su richiesta (503 se non disponibile: la conversazione resta invariata) |
| `/conversations/{id}/notes` | GET/POST | 👤 | Note interne della conversazione (mai visibili al visitatore), con menzioni `@nome` |
| `/conversations/{id}/notes/{note_id}` | DELETE | 👤 | Elimina una nota interna (solo l'autore) |
| `/conversations/{id}/presence` | POST | 👤 | Battito di presenza: chi altro ha aperto la conversazione e chi sta già scrivendo |
| `/conversations/{id}/activity` | GET | 👤 | Registro delle azioni sulla conversazione (risposte, instradamento, note, SLA) |
| `/mentions` | GET | 👤 | Menzioni ricevute dall'operatore (di default solo le non lette) |
| `/mentions/read` | POST | 👤 | Segna come lette alcune menzioni o tutte |
| `/saved-views` | GET/POST | 👤 | Viste salvate dell'inbox (proprie + condivise nel tenant) |
| `/saved-views/{id}` | PATCH/DELETE | 👤 | Aggiorna o elimina una vista salvata (solo il proprietario) |
| `/onboarding/status` | GET | 👤 | Checklist di attivazione calcolata da billing, origin, knowledge base e prima chat |
| `/me/password` | POST | 👤 | Cambia la propria password |
| `/me/rotate-key` | POST | 👤 | Rigenera l'api_key del proprio client |
| `/operator/login` | POST | — | Login operatore (email+password) → token |
| `/operator/logout` | POST | 👤 | Invalida la sessione operatore |
| `/admin/clients` | POST/GET | 🛡️ | Crea/elenca client (con conteggi d'uso) |
| `/admin/clients/{id}/rotate-key` | POST | 🛡️ | Rigenera l'api_key di un client |
| `/admin/clients/{id}/operators` | GET/POST | 🛡️ | Elenca/crea operatori per un client |
| `/admin/operators/{id}` | DELETE | 🛡️ | Rimuove un operatore (e le sue sessioni attive) |
| `/admin/clients/{id}/origins` | POST | 🛡️ | Imposta gli origin widget ammessi per un client |
| `/admin/clients/{id}/plan` | POST | 🛡️ | Assegna un piano a un client |
| `/admin/plans` | GET/POST | 🛡️ | Elenca/crea piani (prezzo, limiti chat/ingest) |
| `/admin/reembed` | POST | 🛡️ | Ri-embedda i contenuti senza embedding (dopo un cambio modello/dim) |
| `/admin/conversations/{id}/debug` | GET | 🛡️ | Vista diagnostica: messaggi + per ogni turno AI cosa è stato recuperato (chunk/distanze/selezione), modello, latenza, token, esito |
| `/admin/audit` | GET | 🛡️ | Log azioni privilegiate (chi/cosa/quando), filtrabile per client |
| `/public/plans` | GET | — | Piani acquistabili per la pagina di registrazione |
| `/signup` | POST | — | Registrazione self-service → Stripe Checkout (prova + carta) |
| `/billing/plans` | GET | 👤 | Piani acquistabili (per l'upgrade self-service dal panel) |
| `/billing/checkout` | POST | 👤 | Avvia il checkout Stripe per il piano scelto → URL di pagamento |
| `/billing/webhook` | POST | — | Webhook Stripe (firma verificata): sincronizza piano e `billing_status` |

## Struttura del progetto

```
wp-aissistant/
├── backend/
│   ├── app/
│   │   ├── main.py        # endpoint FastAPI
│   │   ├── rag.py         # chunking, embedding, retrieval
│   │   ├── llm.py         # wrapper LiteLLM (chat + embed + escalation)
│   │   └── db.py          # modelli SQLModel + init pgvector
│   ├── docker-compose.yml # Postgres+pgvector, Ollama
│   ├── requirements.txt
│   └── test_chunking.py
├── panel/                 # dashboard React/Vite
│   └── src/               # App, Conversations, Tickets, Upload, Stats, api
├── wp-plugin/
│   └── wp-aissistant/     # plugin PHP + assets widget (js/css)
└── website/               # landing marketing statica (index.html + styles.css)
```

### Sito marketing (`website/`)

Landing page promozionale statica, senza build: apri `website/index.html` nel browser (o
servila con qualsiasi web server statico). Deploy consigliato su **Cloudflare Pages** — vedi
[`deploy/CLOUDFLARE-PAGES.md`](deploy/CLOUDFLARE-PAGES.md). Presenta funzionalità, prezzi **a pacchetto**
(Starter/Pro/Business, con toggle mensile/annuale) e **a consumo** (pay-as-you-go), più i link
di **login** e **registrazione**. Le destinazioni di quei link si configurano nell'oggetto
`LINKS` in fondo a `index.html` (attualmente puntano al panel Cloudflare in produzione e al suo flusso
di signup). I prezzi mostrati sono un listino indicativo; il checkout mostra prezzo e
condizioni definitivi configurati in Stripe.

## Roadmap MVP → Produzione

Lo stato attuale è un MVP dimostrativo. Prima della produzione:

### Sicurezza & auth
- [x] `POST /tickets/{id}/reply` ora **richiede e verifica l'`api_key`** e la proprietà del
      ticket. (Prima chiunque con l'ID poteva rispondere impersonando l'operatore.)
- [x] `api_key` spostata dal query param all'header `Authorization: Bearer <key>` (backend,
      panel, widget e plugin WP) così da non finire nei log di server/proxy.
- [x] Autenticazione operatore nel panel: login email+password (hash PBKDF2), token di
      sessione revocabile, operatori legati a un client. (Prima bastava l'`api_key` del client.)
- [x] CORS dinamico (allowlist: origin del panel + origin per-client via
      `/admin/clients/{id}/origins`) al posto di `*`, commutabile con `CORS_ALLOW_ALL`. Il
      binding chiave→sito imponibile è applicato su `/chat` (403 se l'`Origin` browser non è tra
      quelli configurati per il client).
- [x] Rate limiting su `/chat` (per client+IP) e sugli endpoint di ingest (per client),
      via limiter in-memory a finestra fissa. ⚠️ per-processo: per deploy multi-worker
      va spostato su uno store condiviso (Redis).
- [x] Endpoint di registrazione/gestione client (`/admin/clients` + rotate-key), protetti da
      `ADMIN_API_KEY`. (Prima l'inserimento era manuale nel DB.)

### Affidabilità & scalabilità
- [x] Allegati operatore privati su Cloudflare R2: bucket non pubblico, accesso mediato da
      Worker con token server-to-server, isolamento tenant, download autenticato, limite 10 MB
      e cancellazione integrata con eliminazione conversazione/GDPR.
- [x] Ingest asincrono: gli endpoint accodano un `IngestJob` e un worker in background (thread
      avviato dal lifespan, claim con `FOR UPDATE SKIP LOCKED`) fa l'embedding. Stato su
      `/ingest/jobs/{id}`; job orfani rimessi in coda allo startup.
- [x] Indice vettoriale HNSW (opclass cosine) su `chunk.embedding` e `product.embedding` via
      migrazione `0002_vector_indexes`, per scalare il retrieval. (Presente solo via Alembic,
      non con `DB_AUTO_CREATE`.)
- [x] Migrazioni DB con Alembic (`alembic upgrade head`) al posto di `create_all`; migrazione
      iniziale `0001_initial` che riproduce lo schema. `create_all` resta come scorciatoia dev
      dietro `DB_AUTO_CREATE=true`.
- [x] Sostituito il deprecato `@app.on_event("startup")` con un lifespan handler (che avvia
      anche il worker di ingest e ricostruisce l'allowlist CORS).
- [x] Gestione errori LLM/embedding: timeout+retry sulle chiamate Ollama e fallback con
      escalation a operatore (`LLMUnavailableError`) invece di un 500 quando il modello è down.

### Qualità RAG
- [x] Chunking sentence-aware con overlap (era a dimensione fissa) e soglia di distanza cosine
      anche sul retrieval dei chunk; parametri configurabili via env.
- [x] Evaluation suite RAG (`backend/evals/`): dataset JSONL per tenant, verifica delle fonti
      recuperate, outcome atteso, termini richiesti/vietati, report JSON e soglia per CI.
      Il dataset di esempio va adattato alle fonti realmente sincronizzate dal cliente.
- [x] Reranking dei risultati con MMR (Maximal Marginal Relevance): pesca un pool più ampio
      (`RETRIEVE_FETCH_K`) e riordina bilanciando rilevanza e diversità (`MMR_LAMBDA`), usando
      gli embedding già calcolati — nessun modello/infra extra. Testato in unit.

### Osservabilità & operatività
- [x] Logging strutturato (JSON, stdlib): `request_id` per-richiesta propagato via
      contextvar a ogni log line (anche dal worker), header `X-Request-Id` in risposta.
      Eventi chiave loggati: escalation (keyword/modello), LLM irraggiungibile, job di
      ingest falliti. `LOG_LEVEL` configurabile. Health check `/health`.
- [x] Metriche Prometheus su `/metrics`: latenza/conteggio richieste HTTP (per route
      template), più contatori di business (chat, escalation per trigger, esiti job di ingest).
- [x] Notifiche agli operatori sui nuovi ticket via webhook (`OPERATOR_WEBHOOK_URL`,
      payload JSON compatibile Slack/Zapier/n8n, best-effort non bloccante).
- [x] CI (GitHub Actions): test backend (pytest + Postgres/pgvector), migrazioni Alembic
      (`upgrade head` + `downgrade base`) e build del panel, su ogni push/PR.
- [x] CD: dopo una CI verde su `main`, un workflow pubblica l'immagine del backend su GHCR
      (`ghcr.io/andreaem-it/wp-aissistant-backend`, tag `latest` + `sha-<commit>`).
- [x] Deploy live: backend su **Railway** (build automatica dal `Dockerfile` in `backend/`
      ad ogni push su `main`), Postgres+pgvector su **Neon**, chat+embedding su **Cloudflare
      Workers AI**. Dominio Railway generato automaticamente (HTTPS incluso); dominio
      personalizzato non ancora configurato. `CORS_ALLOW_ALL=true` da restringere (allowlist
      per-client via `/admin/clients/{id}/origins`) prima di collegare clienti reali.

### Test & documentazione
- [x] Suite `pytest`: unitari (security/hashing, rate limit, escalation LLM, chunking,
      notifiche) + integrazione endpoint via `TestClient` con LLM mockato (auth,
      escalation, ownership ticket, ingest asincrono, rate limit), gated su
      `TEST_DATABASE_URL`.
- [x] Dockerfile del backend + `docker compose` (db healthy → migrazioni → app) con endpoint
      `/health`; build dell'immagine validato in CI.
- [x] Reverse proxy + TLS documentati in `deploy/` (esempi Caddy e Nginx, guida): terminazione
      TLS, `/metrics` non pubblico, real client IP via `--proxy-headers`/`FORWARDED_ALLOW_IPS`.
- [x] Distribuzione plugin: `wp-plugin/build.sh` genera uno zip versionato (valida che
      docblock e costante `WPAI_VERSION` combacino), `readme.txt` in formato WordPress con
      changelog, e job CI che pubblica lo zip come artifact ad ogni push.
