# Handoff — stato del progetto e regole per chi prosegue

> Documento di sincronizzazione, riallineato il **5 agosto 2026** dopo la chiusura del grosso del
> backlog P2. Serve a chi (persona o assistente AI) riprende il lavoro senza aver seguito la
> sessione precedente. È una guida al **contesto e alle convenzioni**: la verità sul codice sta
> nel codice, la verità sul prodotto in [`competitor-feature-backlog.md`](competitor-feature-backlog.md).
> Se i numeri qui sotto non tornano più, ricontali invece di fidarti: questo file invecchia.

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

**P0 e P1 sono chiusi.** Del **P2 è rilasciato quasi tutto il codice**: modello di canale
unificato, email, WhatsApp, Messenger/Instagram, allegati inbound come file privati, CRM,
help desk esterni, notifiche push operatore e SDK browser pubblicato su npm.

Attenzione alla distinzione che conta:

> Sui canali il codice è completo e testato, ma **nessuno di essi è attivo in produzione**:
> mancano le credenziali dei provider, i webhook registrati e i worker Meta distribuiti.
> "Rilasciato nel repo" non vuol dire "funzionante per un cliente".

Restano scoperti: **marketplace/connettori**, la **parte commerciale** (fatturato, margini,
azioni commerciali nel superadmin) e il filone **Voice**.

Ultimi commit rilevanti (dal più recente):

```
02d0387 feat: let customers manage their own subscription
45ef930 feat: restyle plugin settings and expose licence status
ebc2f2d feat: add the Messenger and Instagram worker
22a3aea feat: forward channel media from the workers
2736482 feat: store inbound channel media as private attachments
f7f0678 feat: package the browser sdk for npm
88a4c39 feat: draft knowledge articles from recurring gaps
36ae576 feat: schedule delayed workflow actions
5c81160 feat: archive and promote proactive experiments
c6a1e2c feat: cluster knowledge gaps locally
```

Dimensioni attuali: **177 endpoint e 7902 righe** in `backend/app/main.py`, **48 tabelle** in
`backend/app/db.py`, migrazioni fino a **`0048`**, 54 file di test backend (**502 test**), 29 test
panel, 7 test plugin. Plugin alla versione **1.2.2**.

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
| `worker.py` | Coda ingest asincrona + classificazione + azioni workflow ritardate | Job idempotenti, retry con backoff, lease recuperabili |
| `business_hours.py` | Calendario lavorativo del tenant | DST-safe e festività italiane calcolate, non hardcodate. Mette in pausa le scadenze SLA fuori orario |
| `attachments.py` | File privati su Cloudflare R2 | Nessun file è mai pubblico: download autenticato e tenant-scoped, cancellazione inclusa nel flusso GDPR |
| `whatsapp.py`, `meta_messaging.py`, `email.py` (canale) | Adapter di canale **provider-neutral** | Il backend parla un contratto normalizzato: credenziali Meta/provider stanno **fuori**, negli adapter Cloudflare. Deduplicazione sull'id messaggio del provider |
| `crm.py`, `helpdesk.py` | Connettori esterni per tenant | Le credenziali del provider **non entrano nel database**: vivono nell'adapter. Qui resta solo la mappatura e l'esito dell'ultimo invio |
| `push.py` | Notifiche push agli operatori | Sottoscrizioni per dispositivo, endpoint scaduti rimossi da soli |
| `billing.py` | Stripe: piani, stato, portale, avvisi | Il webhook è l'**unica** fonte di verità sullo stato dell'abbonamento; un'email fallita non deve far ritentare l'evento a Stripe |
| `deps.py` | Dipendenze condivise: chi chiama, per quale tenant, e l'audit | Non deve conoscere nessuna feature: se un helper serve a una sola area, va con quell'area. È ciò che permette a un router di uscire da `main.py` senza importarlo |
| `routers/` | Un modulo per area dell'API | Uno spostamento **non cambia nulla di osservabile**: stessi path, metodi e risposte. `tests/test_routes.py` blocca i path già spostati |
| `rag.py`, `llm.py`, `security.py`, `ratelimit.py`, `notify.py`, `metrics.py`, `production_config.py` | Preesistenti | — |

### Thread in background (avviati nel `lifespan` di `main.py`)

Quattro: worker ingest, purge retention, monitor SLA, dispatcher webhook. Ognuno ha un env var
per disattivarlo; **i test li disattivano tutti** e chiamano le funzioni direttamente.

Le **azioni workflow ritardate** non hanno un thread proprio: `workflows.dispatch_scheduled()`
gira dentro il loop del worker ingest (`worker.py`). Se disattivi `INGEST_WORKER_ENABLED`,
disattivi anche quelle.

## 4. Modello dati

48 tabelle, migrazioni fino a `0048`.

**Aggiunte in P1** (`0019`→`0029`):

- **Help desk:** `Department`, `DepartmentMember`, `SlaPolicy`, `RoutingSetting`, `SavedView`,
  `InternalNote`, `NoteMention`, `Tag`, `ConversationTag`, `ConversationRating`
- **Automazione/API:** `ApiKey`, `WebhookEndpoint`, `WebhookDelivery`, `Workflow`,
  `WorkflowRun`, `ProactiveRule`
- **Commerciale/qualità:** `LeadForm`, `Lead`, `KnowledgeGapReview`

**Aggiunte in P2 e dopo** (`0030`→`0048`):

- **Omnicanale:** `Contact` (identità del contatto, separata dalla conversazione, chiave
  `client_id + channel + external_id`), `WhatsAppConsent`, `Attachment`
- **Integrazioni:** `CrmConnection`, `CrmSync`, `HelpdeskConnection`, `HelpdeskExport`,
  `PushSubscription`, `PluginInstallation`
- **Operatività:** `SupportSchedule`, `WorkflowScheduledAction`, `ProactiveExperiment`,
  `KnowledgeDraft`
- **Commerciale:** `ModelPrice` (listino per modello, in millesimi di centesimo per milione di
  token, da cui deriva il costo AI per tenant)

`Conversation` ha acquisito: `language`, `priority`, `assigned_operator_id`, `department_id`,
`channel`, `contact_id`, gli stampi SLA (`sla_*`, `first_response_*`, `resolution_*`) e la
classificazione AI (`ai_*`). `Client` porta lo stato di fatturazione (`billing_status`,
`stripe_*`, `subscription_period_end`, `subscription_cancel_at_period_end`), specchiato dal
webhook Stripe **e mai letto chiamando Stripe in linea**.

> Il modello di canale è il vincolo architetturale più importante del progetto: una conversazione
> non presuppone più un visitatore web. Qualunque canale nuovo passa da `Contact` + `channel`,
> non da un campo dedicato.

## 5. Regole di lavoro (non negoziabili)

Vengono dal committente e vanno rispettate in ogni blocco successivo:

0. **Coordinamento multi-agente:** prima di lavorare, seguire `work-locks/README.md`, acquisire
   un lock e pubblicarlo su `main`. Un lock altrui non si oltrepassa.

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

1. **`backend/app/main.py`: 7192 righe, 156 endpoint.** La divisione è **in corso**: due aree
   estratte su nove, da 8016 righe iniziali. Vedi «Dividere main.py» qui sotto.
2. **Widget: 1155 righe in un file.** I testi sono usciti in `chat-i18n.js` (con i primi test
   Node del plugin), il resto no. Senza bundler nel plugin, la strada praticabile è più file
   enqueued con dipendenze, come già fatto per l'i18n.
3. **Le automazioni immediate girano sincrone** dentro la richiesta che emette l'evento. Le
   azioni **ritardate** sono invece già su coda (`WorkflowScheduledAction`, servita dal worker):
   il debito residuo riguarda solo le azioni immediate lente.
4. **Il margine copre solo l'inferenza.** `/admin/costs` prezza i token di `AiResponseLog`, ma
   embedding (ingest), storage R2, email e canali non sono registrati per turno: il margine
   mostrato è un **tetto**. Per chiuderlo serve tracciare anche quei consumi per tenant.
5. **Le intestazioni CORS sono scritte a mano** in `_cors_headers()`, non derivate dalle rotte.
   Hanno già annunciato solo `GET, POST, OPTIONS` mentre l'app instradava 36 rotte PUT/PATCH/
   DELETE, rendendole invisibilmente inutilizzabili dal browser: il server rispondeva `204` al
   preflight e nei log non compariva nulla. Ora c'è `test_cors.py` che confronta i metodi
   annunciati con la tabella di routing, ma la lista resta duplicata.
6. ~~`set_client_plan` scrive `plan_id` senza toccare Stripe.~~ **Risolto**: con un abbonamento
   attivo il cambio piano passa da Stripe e la riga la aggiorna il webhook. La regola vale ora
   per tutte le azioni commerciali — chi agisce chiama Stripe, chi scrive è solo il webhook.

## 9. Cosa fare dopo

Il codice dei canali è scritto: il lavoro che resta è di natura diversa da quello dei mesi
scorsi. Tre filoni, in quest'ordine.

**A. Attivare ciò che è già costruito.** Nessun canale è vivo per un cliente. Serve: credenziali
e numero WhatsApp, deploy dei worker Meta, webhook email presso il provider, portale Stripe
abilitato in dashboard. La business verification di Meta può richiedere settimane: va avviata
prima di tutto il resto, perché è l'unica cosa che non dipende da noi.

> Sui canali c'è anche un problema di **onboarding**: oggi le credenziali per tenant vivono in
> `META_TENANTS_JSON`, un secret statico del worker WhatsApp. Non scala oltre i primi clienti.
> Il pattern giusto è già in casa — l'adapter CRM usa un KV per tenant scritto da `/configure` —
> e va portato sul canale WhatsApp, come passo intermedio verso l'Embedded Signup di Meta.

**B. Completare la parte commerciale.** Fatti: portale Stripe per il cliente con avvisi via email,
viste **Ricavi**, **Costi e margine** e **Crescita**, e le **azioni commerciali**. Restano: azioni
costi di embedding, storage e canali per chiudere il margine (debito 4). Azioni commerciali su
Stripe, funnel di attivazione e clienti a rischio sono fatti: la parte commerciale è coperta
tranne quel pezzo di costi.

> Il listino modelli parte **vuoto**: finché il superadmin non lo compila da *Costi e margine*,
> ogni modello usato compare fra quelli senza prezzo e i costi restano a zero. È voluto — un
> prezzo indovinato sarebbe peggio di un buco dichiarato — ma va fatto prima di fidarsi dei numeri.
> I prezzi Workers AI stanno su
> [developers.cloudflare.com/workers-ai/platform/pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/);
> la chiave da usare è **la stringa esatta che compare fra i modelli senza prezzo**, perché è
> quella che `AiResponseLog` ha registrato. Attenzione: Cloudflare fattura in USD e i piani sono
> in EUR — finché le due valute non coincidono il margine è segnalato come non contabile.

**C. Dividere `main.py` in router** — in corso, una fase per blocco. Vedi sotto.

### Dividere main.py: modello e fasi

Fatto:

- **Fase 1** — `deps.py` (sessione, autenticazione, audit), `routers/commercial.py` (billing e
  viste commerciali), `tests/test_routes.py` a fare da rete.
- **Fase 2** — `routers/developers.py` (chiavi API e webhook). Le utility condivise sono salite
  dove appartengono: `util.py` (`iso`, `bounded_limit`), `deps.py` (`hash_api_key`) e
  `apikeys.py` (scope e formato delle chiavi, condivisi con `/v1` che è rimasto).

Il modello, da ripetere per ogni area:

1. Elencare le funzioni dell'area e **verificare le dipendenze nei due sensi**: cosa serve
   all'area *e* cosa il resto di `main.py` prende **da** lei. Saltare il secondo controllo è
   esattamente ciò che ha rotto `/signup` nella fase 1 — `_stripe_price_for_interval` è finito
   nel router mentre il signup lo usava ancora.
2. Un helper usato da più aree non va nel router: sale in `billing.py`, `deps.py` o dove
   appartiene per dominio. Nessun modulo deve importare da `routers/`.
3. Spostare le funzioni **senza toccarne il corpo**, cambiando solo `@app.` in `@router.`.
4. Aggiungere i path a `COMMERCIAL_ROUTES`/equivalente in `tests/test_routes.py` e far girare
   la suite completa: è la prova che nulla di osservabile è cambiato.

> Attenzione a come si verifica: questa versione di FastAPI tiene un router incluso come **una
> sola voce lazy** in `app.routes`, non come N rotte. Chi ispeziona `app.routes` ingenuamente
> conclude che le rotte sono sparite mentre vengono servite benissimo. `_iter_routes()` in
> `tests/test_routes.py` attraversa i router inclusi: usare quello.

Ordine per le fasi successive, dalla più isolata alla più intrecciata: **API pubblica `/v1`**
→ canali (`/channels`, email/WhatsApp/Meta) → analytics e gap KB → automazioni (workflow,
proattivi, lead) → help desk e inbox → widget e chat → admin residuo.

`/v1` è il prossimo ma non è gratis: dipende ancora da `_build_stats`, `_require_conversation`,
`_notify_visitor_reply`, `_enqueue` e `_whatsapp_channel_status`, tutti condivisi con il resto.
Vanno fatti salire **prima**, un modulo di dominio alla volta, altrimenti il router finirebbe
per importare `main.py`.

Il filone **P3 — Voice** resta separato e non va iniziato prima del go/no-go sul PoC di latenza
descritto in [`voice-roadmap.md`](voice-roadmap.md).
