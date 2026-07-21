# WP AIssistant

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

## Come funziona

1. **Ingest** — Il plugin WP invia al backend i contenuti pubblicati (pagine, articoli,
   prodotti WooCommerce) e le info generali del sito. Il backend li divide in chunk, li
   converte in embedding e li salva in pgvector. Documenti (PDF, immagini con OCR, testo)
   possono essere caricati anche dal panel.
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
uvicorn app.main:app --reload   # http://localhost:8000
```

> **Nota:** non esiste ancora un endpoint di registrazione client. Per creare il primo
> client, inserisci a mano una riga in tabella `client` con `name` e `api_key`.

### Panel

```bash
cd panel
npm install
npm run dev                     # http://localhost:5173
```
Configura il backend con `VITE_API_BASE` (default `http://localhost:8000`). All'avvio
inserisci l'`api_key` del client.

### Plugin WP

Copia `wp-plugin/wp-aissistant/` in `wp-content/plugins/`, attiva il plugin, poi in
**Impostazioni → WP AIssistant** imposta Backend URL e API Key. Usa "Sincronizza ora"
per il primo caricamento della knowledge base.

## Configurazione (backend/.env)

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://rag:rag@localhost:5432/rag` | Connessione Postgres |
| `EMBED_DIM` | `768` | Dimensione embedding (default di `nomic-embed-text`) |
| `CHAT_MODEL` | `ollama/llama3.1` | Modello chat (formato LiteLLM) |
| `EMBED_MODEL` | `ollama/nomic-embed-text` | Modello embedding |
| `LLM_API_BASE` | `http://localhost:11434` | Endpoint LLM (Ollama locale) |

LiteLLM permette di passare a OpenAI / Claude / altri provider cambiando `CHAT_MODEL`,
`EMBED_MODEL` e le relative API key, senza modifiche al codice.

## API principali (backend)

Tutte autenticate via header `Authorization: Bearer <api_key>`.

| Endpoint | Metodo | Descrizione |
|----------|--------|-------------|
| `/ingest/document` | POST | Upload documento (PDF/immagine/testo) nella KB |
| `/ingest/site-page` | POST | Push contenuto pagina/articolo (dal plugin) |
| `/ingest/product` | POST | Push prodotto WooCommerce (dal plugin) |
| `/chat` | POST | Messaggio visitatore → risposta o escalation |
| `/conversations` | GET | Lista conversazioni del client |
| `/conversations/{id}/messages` | GET | Messaggi (polling widget) |
| `/tickets` | GET | Ticket per stato |
| `/tickets/{id}/reply` | POST | Risposta operatore |
| `/stats` | GET | Contatori conversazioni |

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
└── wp-plugin/
    └── wp-aissistant/     # plugin PHP + assets widget (js/css)
```

## Roadmap MVP → Produzione

Lo stato attuale è un MVP dimostrativo. Prima della produzione:

### Sicurezza & auth
- [x] `POST /tickets/{id}/reply` ora **richiede e verifica l'`api_key`** e la proprietà del
      ticket. (Prima chiunque con l'ID poteva rispondere impersonando l'operatore.)
- [x] `api_key` spostata dal query param all'header `Authorization: Bearer <key>` (backend,
      panel, widget e plugin WP) così da non finire nei log di server/proxy.
- [ ] Nessuna autenticazione operatore nel panel (basta conoscere l'`api_key` del client).
- [ ] CORS `allow_origins=["*"]`: restringere a origin per-client.
- [ ] Rate limiting su `/chat` e sugli endpoint di ingest.
- [ ] Endpoint di registrazione/gestione client (oggi inserimento manuale nel DB).

### Affidabilità & scalabilità
- [ ] Ingest sincrono e bloccante: spostare l'embedding su una coda/worker in background.
- [ ] Indice vettoriale (IVFFlat/HNSW) su pgvector per scalare la ricerca.
- [ ] Migrazioni DB (Alembic) invece di `create_all`.
- [ ] `@app.on_event("startup")` deprecato in FastAPI → usare lifespan.
- [ ] Gestione errori LLM/embedding (timeout, retry, fallback).

### Qualità RAG
- [ ] Chunking naïf a dimensione fissa (800 char) → chunking sentence-aware / con overlap.
- [ ] Valutazione qualità retrieval e tuning delle soglie (`PRODUCT_MAX_DISTANCE`, `k`).
- [ ] Reranking dei risultati.

### Osservabilità & operatività
- [ ] Logging strutturato, metriche, health check.
- [ ] Notifiche agli operatori sui nuovi ticket (email/webhook).
- [ ] CI/CD, linting, ambiente di staging.

### Test & documentazione
- [ ] Copertura test oltre `test_chunking.py` (endpoint, RAG, escalation).
- [ ] Documentazione deploy (Dockerfile backend, reverse proxy, TLS).
- [ ] Distribuzione plugin (build `.zip`, versioning, changelog).
