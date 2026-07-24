# WP AIssistant

![CI](https://github.com/andreaem-it/wp-aissistant/actions/workflows/ci.yml/badge.svg)

Assistente AI di supporto clienti per siti WordPress / WooCommerce, basato su RAG.
Un widget di chat flottante risponde ai visitatori usando i contenuti del sito come
knowledge base, ed effettua l'escalation a un operatore umano quando la richiesta
esce dal suo perimetro (rimborsi, reclami, modifiche account, domande fuori contesto).

> **Stato:** MVP funzionante. Vedi [Roadmap MVP → Produzione](#roadmap-mvp--produzione)
> per i lavori necessari prima del rilascio in produzione.

## Architettura

Tre componenti indipendenti:

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
| **Sito marketing** | `website/` | HTML/CSS statico (zero build) | Landing promozionale: feature, prezzi, login/registrazione |

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
4. **Risposta operatore** — L'operatore risponde dal panel; il messaggio torna nella
   conversazione, che rientra in stato `open`. Il widget fa polling per riceverlo.

## Modello dati

- **Client** — tenant, identificato da `api_key`.
- **Chunk** — pezzo di contenuto embeddato (documento o pagina sito).
- **Product** — prodotto WooCommerce strutturato (per renderizzare card nel widget).
- **Conversation** — `open | escalated | closed`.
- **Message** — `user | assistant | operator`.
- **Ticket** — `open | answered | closed`, collegato a una conversazione.
- **Operator** — agente umano che accede al panel; appartiene a un client (password hashed).
- **OperatorSession** — token di sessione opaco emesso al login, eliminato al logout.

### Due tipi di credenziale

- **api_key del client** — machine-to-machine: usata da widget e plugin WP per `/chat` e ingest.
- **Token operatore** — sessione umana: ottenuto via login email+password, usato dal panel.

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
pip install -r requirements.txt
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
pip install -r requirements-dev.txt
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
Configura il backend con `VITE_API_BASE` (default `http://localhost:8000`). All'avvio
accedi con **email e password dell'operatore** (crealo prima via endpoint admin, vedi sopra).

**Pannello superadmin**: `/#admin` (identità separata dal login operatore — mai lo stesso
storage/token). Accesso con `ADMIN_API_KEY` come "password" — tenuta in `sessionStorage`,
non `localStorage`, così non resta su disco oltre la chiusura della scheda. Da lì: creare
client, vedere conteggi d'uso (conversazioni/operatori/chunk/prodotti) per client, gestire
origin CORS, rigenerare api_key, aggiungere/rimuovere operatori, lanciare un re-embed globale,
gestire i **piani** (prezzo, limiti chat/ingest) e assegnarli ai client.

#### Billing: cosa c'è e cosa manca

Le fondamenta sono pronte e funzionanti **senza bisogno di chiavi Stripe**: modello `Plan`
(nome, prezzo mostrato, limiti rate-limit per chat/ingest), ogni `Client` è sempre legato a
un piano (di default "Free", seedato dalla migrazione `0005`), i rate limit su `/chat` e
`/ingest/*` derivano dal piano del client invece che da un valore globale fisso, e il
pannello superadmin permette di creare piani e assegnarli.

**Non ancora fatto** (richiede un account Stripe, anche solo con chiavi di *test*): checkout
per far scegliere/pagare un piano al cliente, webhook per aggiornare `billing_status` /
`stripe_subscription_id` in automatico, fatturazione. I campi `stripe_customer_id`,
`stripe_subscription_id` e `Plan.stripe_price_id` esistono già nello schema in previsione
di questo, ma restano vuoti finché non c'è un'integrazione reale da collegarci.

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
| `PANEL_ORIGINS` | `http://localhost:5173` | Origin del panel ammessi dal CORS (comma-separated) |
| `CORS_ALLOW_ALL` | `true` | `true` riflette qualsiasi Origin; `false` applica l'allowlist |
| `INGEST_WORKER_ENABLED` | `true` | Avvia il worker di ingest nel processo dell'app (coda condivisa via Postgres) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | *(non impostati)* | Abilitano `/billing/*`; se assenti il billing è disattivato — setup in [`deploy/STRIPE.md`](deploy/STRIPE.md) |
| `DOCS_ENABLED` | `false` | Espone `/docs`, `/redoc`, `/openapi.json` (off di default in prod) |
| `METRICS_TOKEN` | *(non impostato)* | Se assente `/metrics` è disabilitato; se impostato richiede `Bearer <token>` |
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
🔑 api_key client · 👤 token operatore · 🔀 entrambi · 🛡️ `ADMIN_API_KEY`.

| Endpoint | Metodo | Auth | Descrizione |
|----------|--------|------|-------------|
| `/health` | GET | — | Liveness probe (nessuna auth) |
| `/metrics` | GET | 🔒 | Metriche Prometheus — disabilitato se `METRICS_TOKEN` non è impostato; altrimenti `Bearer <METRICS_TOKEN>` |
| `/chat` | POST | 🔑 | Messaggio visitatore → risposta o escalation |
| `/ingest/site-page` | POST | 🔑 | Push contenuto pagina/articolo (dal plugin) |
| `/ingest/product` | POST | 🔑 | Push prodotto WooCommerce (dal plugin) |
| `/ingest/document` | POST | 👤 | Upload documento (PDF/immagine/testo) dal panel |
| `/ingest/jobs/{id}` | GET | 🔀 | Stato di un job di ingest (`queued`/`processing`/`done`/`error`) |
| `/conversations` | GET | 👤 | Lista conversazioni del client |
| `/conversations/{id}/messages` | GET | 🔀 | Messaggi (polling widget + lettura panel) |
| `/tickets` | GET | 👤 | Ticket per stato |
| `/tickets/{id}/reply` | POST | 👤 | Risposta operatore |
| `/stats` | GET | 👤 | Contatori conversazioni |
| `/knowledge-base` | GET | 👤 | Documenti/pagine (raggruppati, con conteggio chunk) e prodotti sincronizzati |
| `/me` | GET | 👤 | Profilo operatore: email, nome client, api_key del widget |
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
`LINKS` in fondo a `index.html` (di default puntano al panel su `http://localhost:5173`).
I prezzi mostrati sono di listino promozionale d'esempio, da allineare all'offerta reale.

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
- [~] Tuning delle soglie: cutoff introdotto; resta una valutazione sistematica del retrieval.
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
