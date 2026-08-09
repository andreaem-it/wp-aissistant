# Audit GDPR e residenza dei dati UE

> Stato verificato il **9 agosto 2026**. Questo documento è una valutazione tecnica e
> organizzativa, non un parere legale né una certificazione. «GDPR compliant al 100%» non è un
> titolo rilasciato dal GDPR: la conformità va dimostrata e mantenuta nel tempo.

## Verdetto

WP AIssistant è sviluppato in Italia e incorpora diverse misure di privacy by design, ma **oggi
non può dichiarare che tutti i dati restano nell'Unione europea**, né presentarsi senza riserve
come «100% GDPR compliant».

L'audit iniziale ha trovato tre blocchi tecnici; i primi due sono stati corretti nello stesso
giorno:

1. ~~backend Railway in `sfo`~~ → spostato esclusivamente in `EU West` (Amsterdam), health ok;
2. chat ed embedding usano Cloudflare Workers AI, il cui contenuto non viene usato per training,
   ma per cui Cloudflare dichiara Workers AI **incompatibile con Regional Services**: non abbiamo
   una garanzia che l'inferenza avvenga solo nell'UE;
3. ~~bucket R2 con solo hint `EEUR`~~ → creato bucket omonimo nella jurisdiction `eu`, binding
   aggiornato e Worker distribuito; il bucket precedente è vuoto e resta temporaneamente come
   rollback finché non viene chiuso il collaudo.

`DATA_RETENTION_DAYS=0` è la policy deliberata per i tenant attivi: storico senza scadenza finché
il cliente non sceglie un periodo diverso. È distinta dalla cancellazione completa 90 giorni
dopo la cessazione dell'abbonamento. Redis è stato creato in EU West e collegato al backend;
`STRICT_PRODUCTION_CONFIG=true` è ora attivo: il deploy Railway è riuscito, il controllo delle
variabili riporta zero warning e l'health pubblico è operativo.

## Mappa verificata dei trattamenti

| Flusso / dato | Provider e stato live | Residenza verificata | Esito |
|---|---|---|---|
| Account, conversazioni, messaggi, KB, log AI e ticket | Neon Postgres, host `eu-central-1` | UE, Francoforte | Positivo; conservare evidenza della regione e sottoscrivere il DPA |
| API, RAG, autenticazione, log applicativi e worker backend | Railway, deployment `EU West` | UE, Amsterdam | **Corretto il 9 agosto**: replica `sfo` rimossa, deployment riuscito e health ok; restano DPA e verifica metadata di piattaforma |
| Prompt, cronologia selezionata, risposte ed embedding | Cloudflare Workers AI | Non garantita UE-only | **Bloccante per il claim di residenza**; scegliere inferenza con regione UE vincolante o self-host in UE |
| Allegati privati | Cloudflare R2 privato, jurisdiction `eu` | UE vincolata | **Corretto il 9 agosto**: nuovo bucket vuoto, binding e Worker aggiornati; completare test upload/download/delete e rimuovere il bucket legacy vuoto |
| Email transazionali e canale email | Brevo API | Da verificare per account, piano, log e subprocessori | DPA, regione e retention da documentare; il contenuto email può includere dati personali |
| Pagamenti, fatture e customer portal | Stripe | Trattamento globale con garanzie contrattuali | Trasferimento extra-UE possibile: DPA/SCC, informativa e lista subprocessori obbligatori |
| Error tracking | Sentry disattivato | Nessun invio live | Positivo oggi; rivalutare regione/DPA prima dell'attivazione |
| CRM adapter | Worker Cloudflare attivo | KV/Worker non vincolati all'UE | Limitare i dati, documentare provider e trasferimenti; configurare localizzazione ove disponibile |
| Helpdesk, WhatsApp, Messenger/Instagram | Non attivi | Nessun trattamento live | Inserire nel DPIA e nell'informativa **prima** dell'attivazione; Meta comporta trasferimenti extra-UE |
| Panel e sito | Cloudflare Pages | Rete globale | Il sito statico è a basso rischio; sessioni, log e richieste API restano trattamenti da documentare |
| WordPress del cliente | Hosting scelto dal cliente | Non controllata da WP AIssistant | Chiarire i ruoli: cliente titolare; WP AIssistant responsabile per il SaaS; hosting/plugin restano sotto il controllo del cliente |

## Misure già presenti nel prodotto

- isolamento tenant e test cross-tenant;
- allegati privati con download autenticato;
- export e cancellazione dei dati del visitatore;
- job di retention disponibile nel codice;
- disclosure nel widget che informa di parlare con un'AI;
- URL privacy configurabile dal titolare del sito;
- credenziali dei provider isolate negli adapter;
- minimizzazione dei dati inviati a Sentry (`send_default_pii=False`), oggi disattivato;
- audit delle azioni amministrative e controlli SSRF/webhook.

Queste misure supportano la conformità, ma non sostituiscono base giuridica, informative,
contratti, registro dei trattamenti, DPIA, procedure e verifiche dei fornitori.

## Piano di chiusura P0

### P0-A — Residenza tecnica

- [x] Spostare il backend Railway da `sfo` a `EU West` (Amsterdam), ridistribuire e salvare
  evidenza della regione effettiva.
- [ ] Confermare in Neon Console che progetto, branch, backup e PITR restino in `eu-central-1`.
- [x] Creare un nuovo bucket R2 con jurisdiction `eu`, aggiungere `"jurisdiction": "eu"` al
  binding, migrare gli oggetti, verificare download/cancellazione e poi dismettere il bucket
  con semplice location hint.
- [ ] Sostituire Workers AI per chat/embedding con un provider che offra elaborazione e logging
  contrattualmente vincolati all'UE, oppure eseguire i modelli nel backend UE. Workers AI può
  restare solo se Cloudflare fornisce una garanzia contrattuale specifica sufficiente.
- [ ] Verificare e documentare localizzazione di Worker, KV, log/analytics Cloudflare e routing
  email. La Data Localization Suite è Enterprise e non regionalizza Workers AI.

### P0-B — Configurazione e minimizzazione

- [ ] Esporre ai tenant attivi una retention configurabile; default deliberato senza scadenza.
  La cancellazione dell'intero account 90 giorni dopo la disdetta resta obbligatoria e separata.
- [x] Attivare `STRICT_PRODUCTION_CONFIG=true` e risolvere tutti i warning prima del deploy.
- [ ] Definire retention separate per audit, fatturazione, lead, backup, email e log tecnici.
- [ ] Ridurre log applicativi e provider ai soli metadati necessari; vietare prompt, transcript,
  email e token nei log.
- [ ] Eseguire restore isolato e test end-to-end di export, rettifica, cancellazione e scadenza.

### P0-C — Documenti e governance

- [ ] Pubblicare sul sito informativa privacy, cookie policy/consent se applicabile, termini,
  dati del titolare e contatti privacy. Il sito oggi non contiene pagine legali dedicate.
- [ ] Predisporre DPA art. 28 fra WP AIssistant e ogni cliente, includendo istruzioni,
  sicurezza, cancellazione/restituzione, audit, data breach e subprocessori.
- [ ] Sottoscrivere e archiviare DPA/SCC di Railway, Neon, Cloudflare, Brevo, Stripe e di ogni
  futuro provider; mantenere registro versionato dei subprocessori con preavviso modifiche.
- [ ] Redigere registro dei trattamenti, matrice basi giuridiche e tempi di conservazione.
- [ ] Eseguire DPIA sul supporto AI/RAG, profilazione di intenti/urgenza, lead scoring e canali;
  definire supervisione umana, contestazione e gestione dei dati particolari.
- [ ] Formalizzare procedura data breach entro 72 ore, richieste interessati, accessi del
  personale, onboarding/offboarding e revisione periodica dei privilegi.
- [ ] Chiarire contrattualmente che il cliente è titolare dei dati dei propri visitatori e
  WP AIssistant è responsabile; WP AIssistant resta titolare per account, vendite e sito.

## Claim consentiti

**Adesso:**

- «Sviluppato in Italia».
- «Privacy by design, con export, cancellazione e retention configurabile».
- «Database primario ospitato nell'UE» solo accompagnato dal limite: altri fornitori possono
  trattare dati fuori dall'UE con garanzie contrattuali.

**Da non usare adesso:**

- «Tutti i dati restano in Europa/UE».
- «100% GDPR compliant», «certificato GDPR» o equivalenti.
- «AI interamente europea» o «nessun trasferimento extra-UE».

**Dopo la chiusura e una revisione legale indipendente:**

- «Sviluppato e gestito in Italia, con dati applicativi ospitati e trattati nell'UE».
- «GDPR-ready / progettato per supportare la conformità GDPR», descrivendo misure e
  subprocessori in modo verificabile.

## Evidenze e fonti primarie

- Configurazione live Railway (`railway status --json`, 9 agosto 2026): deployment `sfo`.
- Configurazione live Railway filtrata: Neon `eu-central-1`, Workers AI e Brevo; Redis creato
  e vincolato a EU West il 9 agosto. Retention attivi deliberatamente illimitata; strict mode
  attiva con zero warning e deployment `ae2ba17b-a1b0-4e37-af84-2310d1c7c197` riuscito.
- Configurazione live R2 (`wrangler r2 bucket info`, 9 agosto 2026): location `EEUR`, zero
  oggetti al momento della verifica iniziale; nuovo bucket creato nella jurisdiction `eu` e
  Worker versione `1a83fae5-3c18-48d4-993c-bc9951b8b61b` distribuito.
- Configurazione live Railway dopo la remediation: solo `europe-west4-drams3a`, deployment
  `df3cb429-23c3-4a0d-9369-ad9ae9c2d632` riuscito e `/health` operativo.
- [Railway — regioni](https://docs.railway.com/deployments/regions) e
  [DPA/GDPR](https://docs.railway.com/enterprise/compliance).
- [Neon — sicurezza e cifratura](https://neon.com/docs/security/security-overview) e
  [regioni](https://neon.com/docs/introduction/status).
- [Cloudflare Workers AI — uso dei dati](https://developers.cloudflare.com/workers-ai/platform/data-usage/).
- [Cloudflare Data Localization — compatibilità](https://developers.cloudflare.com/data-localization/compatibility/):
  Workers AI non supporta Regional Services.
- [Cloudflare R2 — location hint e jurisdiction UE](https://developers.cloudflare.com/r2/reference/data-location/).
- [Cloudflare — GDPR e Data Localization Suite](https://www.cloudflare.com/trust-hub/gdpr/).
- [GDPR, testo ufficiale EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj).

## Criterio di completamento

Il blocco può essere dichiarato chiuso solo quando ogni riga della mappa ha: owner, finalità,
base giuridica, categorie di dati, regione verificata, retention, DPA/SCC, lista subprocessori,
misure tecniche e prova di cancellazione. La revisione deve essere ripetuta a ogni nuovo
provider/canale e almeno annualmente.
