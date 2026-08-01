# Handoff — stato del progetto e regole per chi prosegue

> Documento di sincronizzazione scritto il **1 agosto 2026**, dopo la chiusura dell'intero
> backlog P1. Serve a chi (persona o assistente AI) riprende il lavoro senza aver seguito la
> sessione precedente. È una guida al **contesto e alle convenzioni**: la verità sul codice sta
> nel codice, la verità sul prodotto in [`competitor-feature-backlog.md`](competitor-feature-backlog.md).

## 1. Cos'è il progetto

WP AIssistant: assistente AI di supporto clienti per siti WordPress/WooCommerce, basato su RAG,
multi-tenant, venduto in SaaS. Quattro componenti (dettaglio in [`../README.md`](../README.md)):

| Componente | Path | Stack |
|---|---|---|
| Backend | `backend/` | FastAPI, SQLModel, Postgres + pgvector, LiteLLM |
| Panel operatori | `panel/` | React 18 + Vite |
| Plugin WordPress | `wp-plugin/` | PHP + JS/CSS vanilla, **nessun bundler** |
| Sito marketing | `website/` | HTML/CSS statico |

**Produzione live:** backend su Railway (`https://wp-aissistant-production.up.railway.app`),
database Postgres/pgvector su Neon, AI via Cloudflare Workers AI (`bge-m3` per gli embedding,
llama per la chat), panel e sito su Cloudflare Pages. CI/CD su GitHub Actions.

## 2. Stato al momento dell'handoff

**P0 (produzione) e P1 (differenziazione) sono chiusi e rilasciati.** Cicli 2 e 3 del backlog
completati. Tutto è su `main`, con CI, deploy panel e CD immagine verdi, e verificato in
produzione.

Ultimi 13 commit (dal più recente):

```
1168770 feat(i18n): answer visitors in their own language
b3ba361 feat(analytics): add outcome metrics and knowledge gap detection
ef5ddd8 feat(leads): add lead capture forms with consent and scoring
6dfe44a feat(widget): add contextual proactive messages
a597b5f feat(automations): add no-code workflows on events
caf08b2 test: reset the public API rate limiter between tests
5255912 feat(api): add versioned public API and signed webhooks
9af1a72 fix(helpdesk): bound the in-memory presence store
f1991e3 feat(helpdesk): add post-conversation CSAT rating and report
df4d66b feat(helpdesk): add conversation tags and AI classification
c732d53 feat(helpdesk): add internal notes, mentions and presence
d1c39dc feat(helpdesk): add saved inbox views and ordering
7df2715 feat(helpdesk): add SLA policies and automatic routing
```

Dimensioni attuali: 141 endpoint e 5863 righe in `backend/app/main.py`, 34 tabelle in
`backend/app/db.py`, migrazioni fino a `0029`, 41 file di test backend (355 test), 26 test
panel, 7 test plugin. Plugin alla versione **1.1.7**.

## 3. Moduli backend e perché esistono

`main.py` contiene tutti gli endpoint; la logica non banale è stata estratta in moduli, ognuno
con un vincolo di progetto preciso da rispettare se lo modifichi:

| Modulo | Responsabilità | Vincolo da non rompere |
|---|---|---|
| `events.py` | Punto unico di emissione degli eventi conversazione | Webhook e workflow devono vedere **la stessa cosa**; porta la profondità di ricorsione (`depth`) che impedisce le cascate infinite |
| `webhooks.py` | Consegne firmate in uscita, retry, guardia SSRF | `emit()` **non fa I/O**: scrive in coda. La destinazione è scelta dal tenant → URL privati/interni rifiutati alla creazione **e** prima di ogni consegna |
| `workflows.py` | Automazioni no-code (trigger/condizioni/azioni) | Vocabolario **chiuso**, validato al salvataggio: una regola incomprensibile viene rifiutata, mai applicata a metà. Un'azione che fallisce viene registrata, non propagata |
| `tagging.py` | Tag e classificazione AI | La classificazione è **consultiva**: non tocca stato, priorità, assegnazione o SLA. Ogni fallimento lascia la conversazione non classificata, mai etichettata a caso |
| `analytics.py` | Metriche di esito e gap della knowledge base | I gap sono **derivati** dai log a ogni interrogazione, non memorizzati: l'elenco deve accorciarsi da sé quando il contenuto viene aggiunto. Persiste solo la decisione dell'operatore |
| `language.py` | Rilevamento lingua del visitatore | Deterministico, nessuna chiamata AI sul percorso caldo. Se il testo non dice abbastanza si ripiega sul locale, **non si indovina** |
| `i18n.py` | Testi visitor-facing prodotti dal backend | Le risposte deterministiche (ordini, carrello) sono **tradotte a template**, mai rigenerate: un dato d'ordine non deve cambiare cambiando lingua |
| `worker.py` | Coda ingest asincrona + classificazione | Job idempotenti, retry con backoff, lease recuperabili |
| `rag.py`, `llm.py`, `billing.py`, `security.py`, `ratelimit.py`, `email.py`, `notify.py`, `metrics.py`, `production_config.py` | Preesistenti | — |

### Thread in background (avviati nel `lifespan` di `main.py`)

Worker ingest, purge retention, monitor SLA, dispatcher webhook. Ognuno ha un env var per
disattivarlo; **i test li disattivano tutti** e chiamano le funzioni direttamente.

## 4. Modello dati: cosa è stato aggiunto in P1

Migrazioni `0019`→`0029`. Tabelle nuove:

- **Help desk:** `Department`, `DepartmentMember`, `SlaPolicy`, `RoutingSetting`, `SavedView`,
  `InternalNote`, `NoteMention`, `Tag`, `ConversationTag`, `ConversationRating`
- **Automazione/API:** `ApiKey`, `WebhookEndpoint`, `WebhookDelivery`, `Workflow`,
  `WorkflowRun`, `ProactiveRule`
- **Commerciale/qualità:** `LeadForm`, `Lead`, `KnowledgeGapReview`

`Conversation` ha acquisito: `language`, `priority`, `assigned_operator_id`, `department_id`,
gli stampi SLA (`sla_*`, `first_response_*`, `resolution_*`) e la classificazione AI (`ai_*`).

## 5. Regole di lavoro (non negoziabili)

Vengono dal committente e vanno rispettate in ogni blocco successivo:

1. **Compatibilità**: conversazioni e client esistenti non devono rompersi mai.
2. **Ogni tabella/colonna nuova ha una migrazione Alembic reversibile**, verificata con
   `upgrade head` **e** `downgrade base` prima del commit.
3. **Ogni endpoint è tenant-scoped e ha un test cross-tenant.** Convenzione: una risorsa di un
   altro tenant risponde `404`, mai `403`, per non rivelarne l'esistenza.
4. **Mai esporre al visitatore** dati interni, segreti o dettagli tecnici. Le note interne, i
   pesi di scoring dei lead e le chiavi non escono mai verso il browser del visitatore.
5. **UI e testi in italiano**, coerenti col design esistente. Accessibilità (label, ruoli ARIA),
   responsive, stati loading/error/empty espliciti.
6. **Niente conferme ottimistiche**: se un'azione non è andata a buon fine, dirlo. Esempi già
   implementati: il test webhook riporta l'esito HTTP reale; il form CSAT non dice "grazie" se
   l'invio fallisce.
7. **Commit piccoli e descrittivi**; aggiornare `README.md` e
   `competitor-feature-backlog.md` **nello stesso commit** della feature.
8. **Non dichiarare nulla rilasciato prima che CI e deploy siano verdi.** Se una pipeline
   fallisce: leggere i log, capire se è il codice o l'infrastruttura, correggere e ripetere.
9. **Non toccare** modifiche estranee eventualmente presenti nel working tree.
10. Nei messaggi di commit **non aggiungere trailer `Co-Authored-By`**.

## 6. Ambiente di sviluppo locale

I test d'integrazione richiedono Postgres **con pgvector**. Senza `TEST_DATABASE_URL` vengono
**saltati in silenzio**: controllare sempre il numero di test eseguiti, non solo l'assenza di
errori.

```bash
# Postgres 17 dedicato (il pgvector di Homebrew non compila per il 14)
brew install pgvector postgresql@17
PG=/opt/homebrew/opt/postgresql@17/bin
$PG/initdb -D <datadir> -U rag --auth=trust
$PG/pg_ctl -D <datadir> -o "-p 5433" -l <log> start
$PG/psql -h localhost -p 5433 -U rag -d postgres -c "create database rag_test; create database rag;"
$PG/psql -h localhost -p 5433 -U rag -d rag_test -c "create extension vector;"

# venv Python 3.10 (il lock è generato con 3.10)
/opt/homebrew/bin/python3.10 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.lock
```

Comandi di verifica, da eseguire **tutti** prima di ogni commit:

```bash
cd backend
TEST_DATABASE_URL="postgresql+psycopg://rag@localhost:5433/rag_test" pytest -q
DATABASE_URL="postgresql+psycopg://rag@localhost:5433/rag" alembic upgrade head
DATABASE_URL="postgresql+psycopg://rag@localhost:5433/rag" alembic downgrade base

cd ../panel && npm run lint && npm test && npm run build
cd ../wp-plugin && ./build.sh && php -l wp-aissistant/wp-aissistant.php && composer lint
node --test wp-plugin/tests/*.test.js     # dalla radice del repo
```

Dopo il push: verificare con `gh run list` che **CI**, **Deploy panel (Cloudflare Pages)** e
**CD** siano verdi, e sondare la produzione (una rotta nuova deve rispondere `401`, non `404`).
Railway esegue `alembic upgrade head` prima di servire: se risponde, la migrazione è passata.

## 7. Come sono scritti i test

Le fixture stanno in `backend/conftest.py`: `client` (TestClient con schema fresco e LLM
finto), `tenant` (client + operatore con header pronti), `drain` (processa la coda ingest).
Convenzioni utili viste nella suite:

- Ogni feature ha un file `test_<feature>.py` con una sezione di **isolamento tenant** in fondo.
- Le lingue/vocabolari chiusi sono verificati esaustivamente (es. il rifiuto fuori ambito non
  deve promettere un operatore **in nessuna delle sei lingue**).
- Per i tempi si manipola il database direttamente invece di aspettare (`_shift_deadlines`).
- Il fake LLM non produce retrieval realistici: dove serve, si scrive un `AiResponseLog`
  sintetico (vedi `test_analytics.py::_log_turn`). **Attenzione**: `/chat` ne scrive già uno,
  quindi aggiungerne un altro sullo stesso turno raddoppia i conteggi.

## 8. Debito noto (non bloccante, ma reale)

1. **`backend/app/main.py`: 5863 righe, 141 endpoint di sei aree diverse.** Da spezzare in
   router FastAPI per area (helpdesk, analytics, API pubblica, widget, admin, billing). Ogni
   blocco nuovo diventa più lento e rischioso finché resta così. L'omnicanale ne aggiungerebbe
   almeno altre due aree.
2. **Widget: 1130 righe in un file.** I testi sono usciti in `chat-i18n.js` (con i primi test
   Node del plugin), il resto no. Senza bundler nel plugin, la strada praticabile è più file
   enqueued con dipendenze, come già fatto per l'i18n.
3. **Le automazioni girano sincrone** dentro la richiesta che emette l'evento. Va bene per le
   azioni attuali; un'azione lenta o ritardata (es. «dopo 24h senza risposta») va su coda.
4. **Il raggruppamento dei gap KB è esatto**, non semantico: due formulazioni diverse della
   stessa domanda restano righe separate.

## 9. Cosa fare dopo

Il backlog (`competitor-feature-backlog.md`) indica il **P2 — espansione di canale**, con
l'email per prima. Attenzione alla dipendenza architetturale:

> Oggi `Conversation` presuppone un visitatore web identificato da un token di browser. Email,
> WhatsApp e Messenger richiedono un **modello di canale unificato**, con l'identità del
> contatto separata dalla conversazione e il threading. Il backlog mette l'email per prima
> proprio perché è quella che costringe a definire il modello: farla dopo WhatsApp
> significherebbe rifarla.

Ordine consigliato:

1. (Opzionale ma consigliato) Divisione di `main.py` in router — nessuna feature visibile, ma
   abilita tutto il resto.
2. Modello di canale unificato + **email come canale conversazionale**.
3. WhatsApp Business, poi Messenger/Instagram sul modello già definito.
4. Connettori CRM, notifiche push operatore, SDK/widget headless.

Il filone **P3 — Voice** resta separato e non va iniziato prima del go/no-go sul PoC di latenza
descritto in [`voice-roadmap.md`](voice-roadmap.md).
