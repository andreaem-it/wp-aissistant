# Roadmap — widget standalone, CDN e assistente dentro il panel

> Obiettivo: portare WP AIssistant fuori da WordPress (bundle JS configurabile, servito da CDN),
> far scegliere dal panel fra plugin WordPress e integrazione JavaScript con lo stesso
> configuratore, metterlo sul nostro sito e dentro il panel dei clienti come canale di
> assistenza, con un piano interno illimitato per il nostro tenant. Scritto il 9 agosto 2026
> leggendo il codice, non la documentazione: i riferimenti a file e funzioni sono verificati.

## 0. Cosa esiste già (da riusare, non da rifare)

Metà del lavoro è in casa. Prima di stimare qualsiasi cosa:

| Pezzo | Dove | Stato |
|---|---|---|
| Autenticazione widget | `Client.api_key` bearer + binding origin in `deps.rate_limit_chat` | Funziona su qualunque origin registrato: **non serve nulla di nuovo lato auth** |
| Client headless | `sdk/browser` (`createClient`: send, stream SSE, messages, feedback, contact, ticket, rating, lead form) | Pronto per npm, non pubblicato |
| UI completa del widget | `wp-plugin/wp-aissistant/assets/` — `chat-widget.js` (1130 righe), `chat-widget.css`, `chat-i18n.js`, `chat-rules.js` | Funzionante, accoppiata a WordPress in **6 punti soli** (vedi §2) |
| Piano nascosto | `Plan.internal` + `monthly_message_limit = 0` (illimitato) + UI admin di editing piani | Il "piano Illimitato" è **un seed, non una feature** |
| Token d'identità firmato | `wpai_user_token` nel plugin (HMAC, 5 minuti, segreto server-only) | È esattamente il modello da replicare per il contesto nel panel |
| Endpoint del widget | `backend/app/routers/widget.py` | Nessun endpoint nuovo per il widget standalone |

Il lavoro vero è di **estrazione e distribuzione**, più due blocchi nuovi: la configurazione del
widget lato server (§6) e il contesto tenant nel panel (§8). Non è la costruzione di un secondo
prodotto.

**Il buco da conoscere prima di stimare la fase 3:** le 24 opzioni di aspetto del widget
esistono **solo dentro WordPress** (`get_option(WPAI_OPTION)`). Il backend non le conosce, il
panel nemmeno. Un configuratore nel panel non è una schermata da disegnare sopra qualcosa che
c'è: è una schermata più la cosa sotto.

## 1. Fase 0 — Tenant interno e piano Illimitato — **fatta**

Rilasciata con il blocco `internal-tenant-plan`. Cosa è in produzione:

- Piano **`Interno — Illimitato`** (`code = internal_unlimited`, migrazione `0055`): interno,
  gratuito, messaggi e domini illimitati, limiti di frequenza a 600 perché dietro un solo
  `client_id` passerà il traffico di tutti i pannelli dei clienti. Il limitatore resta per IP
  (`chat:{client}:{ip}`), quindi gli utenti restano separati fra loro.
- I nostri tenant sono **esclusi** da ricavi, funnel di attivazione e clienti a rischio; la loro
  spesa è dichiarata a parte in *Costi e margine* (`internal_cost_cents`, `internal_clients`)
  invece di sparire dal margine.
- Etichetta specifica nel pannello admin: un piano interno che concede tutto non può presentarsi
  con la stessa dicitura del segnaposto che non concede niente.

**Due cose scoperte scrivendolo, entrambe più interessanti del piano in sé.**

1. **`default_plan_id()` sceglieva il piano con l'id più basso.** Con un solo piano interno era
   innocuo; con due, su un database in cui l'illimitato nasce per primo — cioè qualunque
   installazione nuova — **ogni nuovo iscritto avrebbe ricevuto accesso illimitato**. Il test
   scritto per presidiare la fragilità l'ha trovata attiva al primo colpo. Rimediato con
   `Plan.code`: un'identità stabile per i piani che il codice deve trovare, al posto di una
   proprietà dell'ordinamento. Il nome non poteva farlo — è modificabile dal pannello.
2. **"Escludere i piani interni" era la regola sbagliata.** Anche il segnaposto è `internal`, ma
   sopra ci sta chi si è registrato e non ha ancora pagato: cioè esattamente la popolazione che
   il funnel di attivazione esiste per misurare. La regola giusta esclude i piani interni **che
   erogano servizio**, e la differenza fra le due è un funnel pulito e un funnel vuoto che mostra
   zero senza dirlo.

**Resta un passo manuale:** creare il nostro tenant in produzione e metterlo su questo piano. È
un'operazione sui dati, non una migrazione — un tenant con la sua `api_key` non si semina in uno
script che gira su ogni ambiente.

## 2. Fase 1 — Estrarre il widget da WordPress (`sdk/widget`) — **fatta**

Rilasciata con il blocco `widget-extraction`. Il widget vive in `sdk/widget`, si costruisce con
esbuild in un IIFE senza dipendenze, e il plugin lo **carica** invece di possederlo.

Cosa è cambiato di sostanziale:

- **Il vocabolario delle opzioni è dichiarato una volta**, in `src/schema.js`. Prima esisteva in
  due posti — la whitelist PHP e dieci liste `.includes(...)` scritte a mano dentro la funzione
  che costruiva il DOM — e la fase 3 ne avrebbe aggiunto un terzo. Un valore fuori vocabolario
  ricade sul default invece di finire nel DOM.
- **Il plugin è un produttore di opzioni** (`wpai_widget_config()`) più l'adapter
  `assets/wp-host.js`, che è l'unico posto rimasto a sapere di carrello WooCommerce, token
  d'identità e frammenti jQuery. Il widget riceve quattro capacità e funziona anche senza:
  niente carrello e niente dati completi dell'ordine, che è il comportamento giusto su un sito
  che non vende da sé.
- **`build.sh` costruisce il bundle e lo copia nel pacchetto.** La convenzione «nessun bundler»
  resta vera dove conta — a runtime, sul sito del cliente — e cade solo in fase di build.

**Il metodo, che è la ragione per cui è andata bene.** Il codice è stato spostato con una
trasformazione meccanica invece che riscritto: stesso criterio della divisione di `main.py`, uno
spostamento non cambia niente di osservabile. Sono cambiati solo i globali (`window.WPAI`,
`WPAI_I18N`, `WPAI_RULES`) e i quattro punti accoppiati alla piattaforma.

**Due cose trovate dai test, che senza non si sarebbero viste.**

1. **Il polling non si fermava mai.** `destroy()` rimuoveva il DOM e lasciava vivo l'intervallo
   che interroga il backend. Su un sito non si nota, perché la pagina cambia; dentro il pannello
   della fase 5 — dove il widget monta e smonta a ogni navigazione — sarebbe rimasto un poller
   per ogni visita, tutti attivi insieme. Il test che monta e smonta l'ha fatto vedere subito.
2. **`cartUrl` era configurato e non usato da nessuno**, e `cartHasItems()` leggeva un cookie
   WooCommerce dentro il widget. Il primo è sparito, il secondo è diventato una capacità
   dell'adapter: senza, le regole proattive che dipendono dal carrello semplicemente non
   scattano, invece di indovinare.

La rete è `test/mount.test.js`: monta in jsdom, verifica classi, chiamata al backend, dominio nel
corpo, rifiuto di licenza che non arriva al visitatore, carrello con e senza adapter, e che il
**codice** del widget non nomini più WordPress — i commenti sì, ed è giusto che lo facciano.

> Il debito 2 dell'handoff («widget: 1130 righe in un file») è chiuso in modo diverso da come era
> previsto: non è stato diviso, è stato spostato e reso configurabile. La parte che disegna resta
> lunga, ma ora è verificabile — che era il vero motivo per cui il debito esisteva.

## 3. Fase 2 — Distribuzione da CDN — **attiva**

Rilasciata con il blocco `widget-cdn`. **R2, non Pages**, e la ragione non è quella che
sembrerebbe: Pages è già in uso per sito e pannello, ma `pages deploy` pubblica *il sito
corrente* e sostituisce la produzione. Qui servono versioni che restano vive per anni — il
plugin pinna una versione con SRI e i siti dei clienti non aggiornano da soli. Su R2 un `put`
aggiunge senza togliere, che è la semantica di un artefatto immutabile.

Cosa è pronto:

- **SRI calcolata insieme al bundle** (`build.mjs` → `dist/integrity.json`) e riportata in un
  file PHP generato da `build.sh`. Nessuna impronta scritta a mano: una che non corrisponde al
  file fa rifiutare lo script al browser, e il sintomo è un widget che sparisce senza un errore
  che spieghi perché.
- **Workflow su tag `widget-v*`**: test, build, controllo che il tag dica la stessa versione del
  pacchetto, pubblicazione della versione immutabile (`max-age` un anno, `immutable`) e
  spostamento dell'alias mobile con cache breve.
- **Verifica finale che il file sia raggiungibile da un browser** e corrisponda all'SRI. È il
  controllo che distingue «il `put` non ha dato errore» da «il widget si carica»: il dominio
  personalizzato del bucket è configurazione a parte, e senza di esso gli oggetti esistono ma
  rispondono solo a richieste firmate.
- **Il plugin carica dal CDN con ripiego locale**: `integrity` + `crossorigin` + `onerror` che
  passa alla copia nel pacchetto. Due protezioni per due problemi diversi — l'SRI copre il file
  sbagliato, l'`onerror` il CDN che non risponde, che è il caso banale e più probabile.
- **`WPAI_WIDGET_CDN` vuoto disattiva tutto** e serve dal pacchetto. È lo stato attuale, ed è
  anche la via d'uscita per chi non vuole richieste a terzi o ha una CSP che blocca l'`onerror`
  inline.

**Pubblicato e verificato il 13 agosto 2026.** `widget/0.1.0/` risponde `200` con
`cache-control: public, max-age=31536000, immutable`, e l'impronta del file servito coincide con
l'SRI calcolata in build. Il plugin punta al CDN (`WPAI_WIDGET_CDN`) sulla versione fissa.

> **Una diagnosi sbagliata, per memoria.** Avevo concluso che il dominio non fosse collegato al
> bucket perché rispondeva `404` con una pagina HTML e la favicon di Cloudflare, e l'avevo letta
> come la 404 di un progetto Pages. È invece ciò che R2 restituisce per un oggetto mancante: le
> due sono indistinguibili da fuori. L'unico controllo che decide è mettere un oggetto e
> chiederlo — che è esattamente ciò che il workflow fa, ed è il motivo per cui il passo di
> verifica esiste.

**L'ordine di rilascio conta.** Il plugin punta a una versione fissa: se quella versione non è
sul CDN, ogni sito cade sul ripiego locale **in silenzio** e la distribuzione non serve a niente.
Prima il tag `widget-v*`, poi la release del plugin. `build.sh` avvisa quando la versione che sta
per impacchettare non è pubblicata — avvisa e non fallisce, perché costruire il plugin deve
funzionare anche offline.

## 4. Perché dal CDN — e cosa il CDN non protegge

La scelta di servire sempre il widget dal CDN è giusta, ma va adottata per i motivi veri,
perché costruire su una premessa di sicurezza sbagliata porta a rinunciare ai controlli che
servono davvero.

**Cosa compra il CDN**

1. **Un artefatto solo.** È la stessa garanzia per cui esiste la fase 1: nessuna divergenza fra
   il widget del plugin e quello standalone.
2. **Il ciclo di aggiornamento.** Una correzione raggiunge tutti i siti subito, invece di
   attendere una release del plugin *e* che ogni cliente aggiorni — su WordPress, mesi. È
   l'argomento più forte, ed è sufficiente da solo.
3. **Un plugin più piccolo.** Meno PHP, meno superficie da rivedere, meno da mantenere.

**Cosa il CDN non compra: nulla contro le manomissioni.** Il widget è codice client-side
pubblico, servito senza autenticazione: si scarica con un `curl` e si auto-ospita. Non contiene
segreti — non può, gira nel browser di un visitatore. Un plugin *nulled* non ha bisogno del
nostro JavaScript: ha bisogno di una `api_key` che funzioni. Il controllo è e resta
**server-side**.

Dove il buco c'è davvero, e come si chiude, è in §5: la licenza legata al dominio. Nessuna di
quelle contromisure dipende dal CDN, e insieme valgono molto più di dove è ospitato un file.

**Distribuzione: solo auto-ospitata, niente WordPress.org.** Deciso. Cade quindi il vincolo
della linea guida 8 sul codice eseguibile remoto: il caricamento dal CDN non deve più passare da
nessuna revisione, e il `readme.txt` resta utile come documentazione ma non come formato
obbligatorio.

> Nota fattuale, perché la decisione regga sui motivi giusti: un plugin che richiede un piano a
> pagamento su un servizio esterno **non è** escluso dal repository — i widget di chat SaaS ci
> stanno, richiedendo account e abbonamento. La porta non è chiusa dalle regole, la stiamo
> chiudendo noi. Ci sono buoni argomenti indipendenti (nessuna coda di revisione, controllo
> pieno sulla distribuzione, libertà sul CDN) e il costo è reale — WP.org è il primo canale di
> scoperta per un prodotto WordPress. Vale solo la pena che sia una scelta, non un
> fraintendimento.

**Il costo dell'auto-distribuzione:** senza il repository, gli aggiornamenti del plugin non
arrivano da soli. Serve un **update server** (`site_transient_update_plugins`) o i clienti
restano sulla versione che hanno installato per sempre. Il CDN attenua molto il problema — il
widget si aggiorna da sé — ma il PHP no: shim, adapter WooCommerce e sincronizzazione dei
contenuti restano fermi. Va messo in conto nella fase 2, insieme allo zip su URL stabile.

**I costi da accettare consapevolmente**

1. **Un solo punto di rottura per tutti i clienti insieme.** Oggi un guasto è per-sito; da qui
   in poi il nostro CDN è nel percorso critico di ogni sito servito. La copia di riserva nel
   plugin copre i siti WordPress; per l'integrazione JavaScript pura non c'è rete, e va detto
   nella documentazione invece di scoprirlo insieme al cliente.
3. **Privacy.** Il browser di ogni visitatore contatta il nostro CDN: il suo IP arriva a noi.
   Va nell'informativa e nel DPA, e coerentemente con l'audit del 9 agosto **senza claim di
   residenza UE**. Alcuni clienti (settore pubblico su tutti) obietteranno allo script di terze
   parti: per loro serve una risposta preparata, non improvvisata.
4. **CSP.** I siti con una Content-Security-Policy stretta devono aggiungere il nostro CDN a
   `script-src`. Va nella pagina di installazione del panel, non solo nei documenti: è il secondo
   motivo per cui "ho incollato lo snippet e non appare niente".

## 5. La licenza è legata al dominio

**Regola di prodotto:** il dominio su cui gira il widget è un parametro di configurazione
obbligatorio, e un widget su un dominio non registrato **non funziona**. Una licenza non copre
venti siti.

**Chi fa cosa, perché non si ripeta l'errore del CDN.** Il dominio dichiarato nella
configurazione e l'applicazione della licenza sono due cose diverse:

- il **parametro in configurazione** serve a costruire la callback dell'order lookup (è già
  `WPAI.siteUrl` oggi, e il commento nel plugin spiega perché l'header non basta: un'
  installazione in sottocartella produrrebbe una URL sbagliata) e a **fallire subito e in
  chiaro** — "dominio non configurato" — invece di un `403` remoto senza spiegazione;
- l'**applicazione** è server-side sull'header `Origin`, che imposta il browser e la pagina non
  può falsificare. Un valore che scrive il cliente non vincola il cliente: se ci affidassimo al
  parametro in configurazione staremmo rifacendo l'errore del CDN.

**Onestà sul limite.** `Origin` è falsificabile da un client non-browser (`curl -H`). Questo
ferma il caso vero — la licenza copiata su venti siti, che è gente che duplica uno snippet — non
l'attaccante determinato. Per la prova forte di possesso del sito esiste già `PluginInstallation`
(challenge verificata con `_verify_plugin_site`); l'equivalente per il JavaScript puro è una
verifica di dominio periodica: file sotto `/.well-known/` o meta tag, ricontrollata nel tempo.
Da fare solo se il caso lo richiede — ma sapendo che senza di essa il controllo è dissuasivo,
non probante.

**Modello dati.** Oggi `Client.allowed_origins` è una stringa separata da virgole. Con la licenza
legata al dominio i domini vanno **contati, datati e mostrati**, quindi diventano righe:
`ClientOrigin(client_id, origin, kind, status, verified_at, first_seen_at, last_seen_at)` con
`kind ∈ {live, staging}` e `status ∈ {registered, observed}`, unicità su `(client_id, kind)`.
`normalize_origins` resta il punto unico di normalizzazione; `cors.rebuild_allowed_origins` va
aggiornato perché oggi legge la colonna di testo.

Su `Plan` serve **`max_live_origins`** (default `1`, `0 = illimitato` per coerenza con
`monthly_message_limit`, piano interno a `0`) — un numero e non una costante, perché il primo
cliente agenzia o multisite chiederà più domini live, e quella è una leva di prezzo che vogliamo
avere già pronta invece di doverla ricostruire.

### Gli slot: un live, uno di staging, i locali gratis

| Tipo | Quanti | Regola |
|---|---|---|
| **Live** | 1 (dal piano) | Il dominio di produzione |
| **Staging** | 1 | Deve avere una **etichetta di sviluppo** nel nome (sotto) |
| **Locali** | illimitati, non contati | `localhost`, `127.0.0.1`, `*.local`, `*.test`, `*.localhost` |

I locali non consumano slot e non si negano mai: non hanno valore commerciale, e bloccarli
rompe l'ambiente di sviluppo di ogni cliente in cambio di niente.

**Il vocabolario delle etichette di staging è chiuso e validato al salvataggio**, come i
vocabolari di `workflows.py`: `staging`, `stage`, `dev`, `develop`, `development`, `demo`,
`test`, `testing`, `preprod`, `preproduction`, `preview`, `uat`, `qa`, `sandbox`, `beta`.

**Il confronto è per etichetta DNS, mai per sottostringa.** `dev.esempio.it` contiene
l'etichetta `dev`; `devoto.it` e `demolizioni.it` contengono la sottostringa e non sono ambienti
di sviluppo. Una regola scritta con `in` invece che sulle etichette regala uno slot gratis a
chiunque abbia un dominio che comincia per "dev" o "demo", e non se ne accorge nessuno. Vale
qualunque etichetta del nome, non solo la prima: `shop.staging.esempio.it` è valido.

**La parola chiave da sola non basta, e questo è il punto da non saltare.** `demo.altrosito.it`
rispetta la convenzione ed è un secondo sito commerciale a tutti gli effetti: la regola così
com'è non lega lo slot al cliente, lo lega a una convenzione di nomi. Il vincolo che serve è che
lo staging sia **un sottodominio del dominio live** — `staging.esempio.it` per `esempio.it` —
e l'etichetta diventa il controllo secondario.

Con un'eccezione necessaria, altrimenti rompiamo installazioni oneste: molte agenzie ospitano lo
staging altrove — `esempio.wpengine.com`, `esempio.pantheonsite.io`, `esempio.kinsta.cloud`,
`esempio.vercel.app`, `esempio.netlify.app`, `*.ngrok.io`, `*.ddev.site`. Quindi lo staging è
valido se **è sottodominio del live con etichetta di sviluppo**, *oppure* se sta su un suffisso
di una **lista chiusa di piattaforme di sviluppo** che manteniamo noi. Tutto il resto si rifiuta
spiegando perché.

**Le altre equivalenze**, da fissare prima di implementare o le decide il codice per caso:

| Caso | Regola |
|---|---|
| `esempio.it` e `www.esempio.it` | Stesso sito: **un solo slot**, entrambi ammessi |
| `http://` e `https://` | Stesso sito; in produzione si accetta comunque solo `https` |
| `shop.esempio.it` e `blog.esempio.it` | Due live distinti → con un solo slot, **serve un piano superiore**. È una decisione di prezzo, va scritta nel listino prima che la scopra un cliente |
| WordPress multisite | Un'installazione, N domini: è il caso che collide di più con "un solo dominio live". Serve una risposta commerciale, non un'eccezione tecnica |

**Il cambio del dominio live va reso self-service.** I clienti cambiano dominio davvero: rebrand,
migrazioni, e soprattutto il passaggio da staging a live al lancio. Uno slot unico senza un modo
di cambiarlo trasforma ogni migrazione in un ticket, e penalizza gli onesti molto più dei
parassiti. Cambio dal panel con traccia nell'audit e un raffreddamento (per esempio un cambio
ogni 7 giorni): la cronologia rende evidente chi lo usa per ruotare fra venti siti, che è
esattamente il comportamento che vogliamo vedere invece di impedire a tutti.

**Le conversazioni di staging non vanno mescolate a quelle vere.** Un `ClientOrigin.kind` c'è
già: le conversazioni che arrivano da staging vanno marcate e tenute fuori da statistiche, CSAT
e viste commerciali per impostazione predefinita. Non è anti-abuso, è qualità del prodotto —
altrimenti le prove di un tema in staging inquinano i numeri su cui il cliente decide.

### Quanto è già chiuso: correzione dopo la verifica in produzione

Una prima stesura di questo documento diceva che passare a fail closed avrebbe spento il widget
a quasi tutti i clienti. **Non è così, e la differenza cambia le priorità.** Il backend di
produzione applica la CORS in modo stretto: un preflight con un `Origin` sconosciuto riceve
`403` (verificato il 10 agosto 2026 contro il backend live; `CORS_ALLOW_ALL` è quindi `false`
come prescrive `production_config.py`).

Conseguenze, tutte controintuitive rispetto a com'era scritto prima:

1. **Il traffico browser da un dominio non ammesso non arriva mai all'applicazione.** La chiamata
   a `/chat` porta `Authorization` e JSON, quindi non è una richiesta semplice: il browser manda
   prima il preflight, che viene rifiutato. Un cliente il cui dominio non è in allowlist ha già
   oggi un widget che **non funziona** — non uno che funziona e che romperemmo noi.
2. **La licenza per dominio, lato browser, è già in gran parte applicata** — non dalla riga che
   guardavamo, ma dall'allowlist CORS. Il "venti siti con una licenza" fatto da un browser oggi
   fallisce già al preflight.
3. **Restano due varchi veri.** L'allowlist CORS è **globale**: un origin registrato da un
   cliente qualsiasi passa il livello browser, e poi `rate_limit_chat` rifiuta solo se è il
   *chiamante* ad avere origin configurati — quindi "dominio registrato da un altro tenant +
   chiamante con `allowed_origins` vuoto" passa. E soprattutto: alle chiamate **senza header
   `Origin`** la CORS non si applica affatto, perché non è un browser a farle. Quel varco è
   intero, ed è il modo realistico di usare una chiave pubblica rubata.

Quindi il lavoro cambia bersaglio: meno "non spegniamo tutti", più **chiudere il varco
server-side** e misurare quanti tenant hanno davvero `allowed_origins` vuoto *e* traffico
recente — una query da fare in produzione prima di decidere la data di applicazione, non una
supposizione.

### Cosa ha detto l'osservazione, e perché la gradualità è saltata

Tre giorni in produzione, e il risultato utile non è quello che l'osservazione doveva misurare
ma un fatto che rende la misura inutile: **zero righe nuove, perché non è passato traffico chat
dopo il rilascio.** Il parco è di quattro tenant, tutti di prova; l'unico che ha mai avuto
traffico (6 messaggi il 4 agosto, 6 il 7) ha già il dominio registrato dall'installazione
WordPress verificata. Nessuno usa oggi il prodotto in modo da poter essere interrotto.

Aspettare altri giorni non avrebbe prodotto dati: **non c'è traffico da osservare**. E la stessa
constatazione che rende inutile l'osservazione rende sicura l'applicazione, ora, prima dei
clienti veri. La sequenza a scaglioni — osservazione, conferma, preavviso, data — era il modo
giusto di trattare un parco popolato; applicarla a quattro tenant di prova sarebbe stato un
rituale, non una cautela. **Applicato subito.** La sequenza resta scritta qui perché serve al
prossimo cambiamento di questo tipo, non a questo.

**Stato dopo l'applicazione** (blocco `domain-licence-enforcement`):

- `deps.rate_limit_chat` fallisce **chiuso**: niente domini registrati o niente header `Origin`
  → `403` con il motivo per esteso.
- `ClientOrigin` è la sorgente di verità per licenza, allowlist CORS e callback dell'order
  lookup. `Client.allowed_origins` sopravvive solo come **specchio** per il pannello admin,
  scritto da `origins._mirror()` e letto da nessuna decisione: si toglie quando il pannello sarà
  passato a `/account/origins`.
- Entrambi i varchi di §4 sono chiusi: quello dell'allowlist globale (la copertura si valuta ora
  sui domini **del chiamante**) e quello delle chiamate senza `Origin`.
- Registrazione self-service da `/account/origins`, con slot visibili e cambio del dominio live
  soggetto a raffreddamento e audit.
- **L'installazione del plugin registra il dominio da sé.** Senza questo ramo il fail closed
  avrebbe reso impossibile l'onboarding di ogni cliente WordPress nuovo: il primo passo è
  installare il plugin, e per farlo serviva un dominio già registrato. La fiducia viene dal
  challenge HMAC, che prova il possesso del sito ed è una prova più forte di un form. Vale solo
  a slot libero: a slot pieno il dominio non viene sostituito di nascosto.

**Il cerchio è chiuso** (blocco `domain-licence-visibility`). Il rifiuto non è più muto:

- **Pannello**, *Impostazioni → Siti e licenza*, prima scheda e predefinita perché è dove si
  finisce quando il widget non compare: domini registrati con la loro provenienza, slot residui,
  domini **visti in uso ma non registrati**, e il motivo del backend mostrato per esteso quando
  una registrazione viene rifiutata. Sostituire il dominio di produzione chiede conferma
  nominando il sito che perderà il widget — con un solo slot "aggiungi" **sostituisce**, e
  chiamarlo aggiunta è il modo di far perdere a qualcuno il proprio sito senza volerlo.
- **Widget**: su un `403` di licenza scrive il motivo in console per chi installa, e al
  visitatore mostra un testo neutro che **non** lo invita a riprovare — riprovare non
  cambierebbe nulla — e non nomina licenza, dominio né codici di errore. Verificato nelle sei
  lingue, con la controprova che l'errore di rete generico continua invece a invitare al
  ritentativo.
- Il client del pannello conserva ora il `detail` del backend (`api.js`): senza, la spiegazione
  scritta lato server moriva nel trasporto e la UI doveva inventarsi un messaggio generico.

Resta fuori, come previsto, l'errore leggibile nel widget **standalone**: nascerà con
l'estrazione in `sdk/widget` (fase 1), che è dove quel codice andrà a vivere.

**Rifiuto leggibile, in tre posti.** Il messaggio HTTP dice quale dominio è stato rifiutato; il
panel mostra lo stato della licenza (dominio non registrato, slot esauriti) senza far leggere
una console a nessuno; il widget lo scrive in console per lo sviluppatore. **Al visitatore non
appare nulla di tutto questo** — non deve sapere che esiste una licenza, e la regola 4 vale
anche qui.

**E chiude anche il buco di sicurezza.** Le due falle di `deps.rate_limit_chat` — nessun
controllo con `allowed_origins` vuoto, controllo saltato senza header `Origin` — spariscono
entrambe con questa regola: fail closed sul primo, e sul percorso widget una richiesta senza
`Origin` va rifiutata (il widget lo manda sempre; chi integra da server ha `/v1` con `ApiKey` e
scope, che è la porta giusta). La licenza per dominio e la chiusura del buco sono lo stesso
lavoro.

## 6. Fase 3 — Installazione nel panel: plugin WordPress o JavaScript

Il cliente sceglie come installare, e se sceglie JavaScript configura l'aspetto dal panel e
riceve lo snippet già personalizzato.

**Dove vivono oggi le opzioni — il vincolo di partenza.** Tutte e 24 le opzioni di aspetto (più
le 4 di orario) stanno dentro WordPress: `wpai_opt`/`wpai_setting` leggono
`get_option(WPAI_OPTION)`, la whitelist è in `wpai_sanitize_settings`. **Il backend non ha
nessuna tabella di configurazione del widget** e il panel non ne sa nulla. Unica eccezione, ed è
il precedente da seguire: gli **orari di supporto** salgono già al backend (`SupportSchedule`,
`PUT /plugin/support-schedule`). La direzione plugin → backend esiste, quella panel → sito no.

**Cosa costruire**

1. ~~Tabella `WidgetConfig` per tenant~~ **fatta** (migrazione `0056`): una riga per cliente,
   configurazione in JSON perché il vocabolario cambia con il widget e una colonna per opzione
   trasformerebbe ogni stile del pulsante in una migrazione. Nessun backfill dai siti WordPress:
   inventare una riga con i default farebbe apparire "configurato" ciò che non lo è, e al primo
   salvataggio dal pannello sovrascriverebbe l'aspetto vero del loro widget con valori mai scelti.
2. ~~Endpoint tenant-scoped di lettura e scrittura~~ **fatti**: `GET`/`PUT /account/widget-config`,
   sessione operatore — la chiave pubblica del widget sta in ogni pagina e non deve poter
   riconfigurare niente. Il **vocabolario viaggia con la configurazione**, così il pannello
   costruisce i menu a tendina da lì invece di riscrivere la lista.

> **Il vocabolario è uno solo, in tre linguaggi.** `sdk/widget/src/schema.js` resta la
> dichiarazione; la build genera `sdk/widget/schema.json`, versionato, che il backend legge. Due
> test chiudono il giro: uno in Python confronta la copia in memoria con l'artefatto, uno in
> JavaScript confronta l'artefatto con lo schema — senza il secondo, una modifica a `schema.js`
> senza rebuild lascerebbe backend e artefatto d'accordo fra loro e in disaccordo con il widget.
> Verificato provocando la divergenza: il test fallisce.

> **Rifiutare, non correggere.** Il widget ripiega sul default per un valore fuori vocabolario,
> perché deve funzionare comunque; il configuratore lo rifiuta con il motivo. Un'impostazione
> salvata che non ha alcun effetto è peggio di un errore — il cliente crede di aver scelto
> qualcosa e vede il widget di prima.
3. Pagina **Installazione** nel panel, con la scelta esplicita:
   - **WordPress** → download dello zip, chiave da incollare, e stato reale dell'installazione
     (`PluginInstallation` esiste già e sa se il sito è verificato).
   - **JavaScript** → configuratore, anteprima, snippet.
4. Configuratore con le stesse opzioni della pagina del plugin e **anteprima dal vivo**. Dopo la
   fase 1 l'anteprima monta il widget vero invece di un mock: è l'argomento più forte per fare
   questa fase dopo l'estrazione e non prima.
5. Snippet generato, con le opzioni in chiaro:

```html
<script>
  window.WPAissistantConfig = {
    apiKey: "CHIAVE_PUBBLICA",
    apiBase: "https://backend.wpaissistant.it",
    appearance: { color: "#635bff", theme: "light", position: "right", launcherStyle: "pill" /* … */ },
    texts:      { title: "…", subtitle: "…", welcome: "…", aiDisclosure: "…" },
    support:    { enabled: true, days: [1,2,3,4,5], start: "09:00", end: "18:00", timezone: "Europe/Rome" }
  };
</script>
<script async src="https://cdn.wpaissistant.it/widget/v1/wpai-widget.js"></script>
```

6. **Registrazione dei domini dentro lo stesso flusso.** È il primo passo del configuratore, non
   un'impostazione avanzata: senza dominio registrato il widget non funziona (§5). In produzione
   `CORS_ALLOW_ALL=false` (verificato in `production_config.py`, `deploy/README.md` e i due
   compose), e oggi `allowed_origins` si modifica **solo** da `/admin/clients/{id}/origins`, cioè
   dal superadmin: **un cliente non può registrare da sé il dominio del proprio sito**. Serve:
   - endpoint tenant-scoped sui propri domini, con la normalizzazione di `normalize_origins`,
     niente wildcard e `cors.rebuild_allowed_origins()` dopo la scrittura;
   - **gli slot visibili come sono**: un dominio live, uno di staging, i locali gratis (§5), con
     l'errore esplicito quando il live è occupato — e il collegamento al cambio piano, perché è
     esattamente il momento in cui il cliente ha un motivo per farlo;
   - il campo staging che **spiega la regola mentre la applica**: se il cliente scrive
     `demo.altrosito.it` il messaggio dice che lo staging dev'essere un sottodominio di
     `esempio.it` o stare su una piattaforma di sviluppo riconosciuta, non un generico "non
     valido";
   - il **cambio del dominio live** self-service, con la cronologia dei cambi;
   - i domini **osservati ma non confermati** in evidenza («abbiamo visto traffico da
     `staging.esempio.it`: confermalo o rimuovilo»), che è anche il meccanismo di migrazione;
   - **test d'installazione** che dice se quel dominio risponde davvero;
   - nel widget, errore leggibile su `403` invece di un fallimento muto (regola 6) — in console
     per lo sviluppatore, **mai** al visitatore.

**La conseguenza da dire subito, non dopo.** Con le opzioni in chiaro nello snippet, cambiare
l'aspetto significa **ricopiare lo snippet**. Per un'agenzia va bene; per l'utente finale è
esattamente ciò che produce «l'ho cambiato nel panel e sul sito è rimasto uguale». Due
mitigazioni, entrambe piccole perché la configurazione è comunque già persistita:

- il panel mostra sempre lo snippet aggiornato e **dice** che va ricopiato dopo ogni modifica;
- **modalità gestita** opzionale: lo snippet contiene solo `apiKey` e `apiBase`, il widget legge
  la configurazione all'avvio. Costa una richiesta in più al caricamento — mitigabile servendo
  `/widget/{key}.js` dal CDN con TTL breve — e in cambio l'aspetto si cambia dal panel senza
  toccare il sito. È un interruttore nello snippet generato, non un secondo prodotto.

**Il vincolo architetturale della fase.** Le 24 opzioni sono un **vocabolario chiuso**, e oggi la
whitelist esiste una volta sola: `wpai_sanitize_settings`. Se il panel diventa un secondo
produttore, quella lista si duplica in JavaScript e in Python — cioè il debito 5 dell'handoff
(intestazioni CORS scritte a mano, lista duplicata, 36 rotte invisibilmente irraggiungibili e
nessun errore nei log). Il vocabolario va dichiarato **una volta** in `sdk/widget` — valori
ammessi e default — il backend valida contro quello, il PHP ne genera la propria copia in build,
e un test confronta le tre liste e fallisce quando divergono. Aggiungere un `launcher_style`
deve restare una riga in un posto solo.

**Decisione da mettere per iscritto ora, da eseguire subito dopo.** Quando il panel sa
configurare l'aspetto, per un cliente WordPress le stesse 24 opzioni esistono in due posti: la
pagina del plugin e il panel. Oggi non è un problema perché il panel non le conosce; da questa
fase lo diventa. Il finale giusto è **il panel come sorgente di verità e il plugin che legge dal
backend**, con override locale opzionale — la direzione opposta a quella odierna degli orari di
supporto. Non va fatto in questo blocco, ma va deciso qui: ogni settimana in cui i due posti
coesistono senza una regola produce clienti che hanno configurato quello sbagliato e un
supporto che non sa quale dei due sta guardando.

## 7. Fase 4 — Il widget sul nostro sito

Piccola, e ci rende utenti del nostro prodotto.

1. `website/index.html` carica lo snippet CDN con la chiave del nostro tenant.
2. `website/_headers` oggi non ha CSP: se ne aggiungiamo una (andrebbe fatto comunque) deve
   ammettere il CDN e il backend. Il file va toccato **insieme** allo snippet, non dopo.
3. Ingest della nostra knowledge base sul nostro tenant: pagine del sito, prezzi, FAQ e i
   documenti d'uso — **non** il repository. Un README interno finito nel retrieval risponde a un
   potenziale cliente con dettagli d'implementazione.
4. L'escalation dal sito arriva nella **nostra** inbox: gli operatori siamo noi. È il primo uso
   reale del help desk dall'altra parte del banco.
5. Privacy: il widget raccoglie messaggi di visitatori. Informativa aggiornata e **nessun claim
   di residenza UE**, come stabilito dall'audit del 9 agosto.

## 8. Fase 5 — L'assistente dentro il panel del cliente

Qui c'è l'unico blocco architetturalmente nuovo. La knowledge base è **la nostra
documentazione**; il contesto è **il tenant loggato**. Due tenant in gioco nella stessa
conversazione, ed è esattamente il punto in cui si sbaglia.

> **Il tenant che risponde siamo noi. Il tenant del cliente è un soggetto, non un chiamante.**
> Il widget nel panel usa la nostra `api_key` pubblica; il contesto del cliente non arriva mai
> dal browser, viene derivato dal backend a partire da un token firmato.

**Meccanismo del contesto** — lo stesso schema di `wpai_user_token`, che è già in produzione e
già ragionato:

1. `POST /panel/assistant/token`, autenticato dalla **sessione operatore**, restituisce un token
   HMAC di 5 minuti che contiene `client_id`, `operator_id` e scadenza. Firmato con un segreto
   server-only: **mai** con una `api_key` pubblica — l'errore che il commento nel plugin
   (`wpai_token_secret`) descrive per esteso.
2. Il widget lo passa a `/chat` in un header dedicato.
3. Il backend verifica la firma e costruisce il blocco di contesto **leggendo il database**, non
   fidandosi di un solo campo del client.

**Il contesto è una whitelist, non un dump.** Campi ammessi: piano e `billing_status`, numero di
documenti indicizzati e data dell'ultimo ingest, installazione plugin verificata sì/no, origin
configurati sì/no, canali attivi, conversazioni aperte e senza risposta. Questo è ciò che serve
per rispondere «il widget non compare perché non hai registrato l'origin del sito» — la domanda
per cui l'assistente esiste. Fuori: contenuti delle conversazioni, dati dei contatti, chiavi.
Ogni lettura cross-tenant va nel log d'audit: è un accesso ai dati di un cliente fatto da un
sistema nostro, e deve essere ricostruibile.

**Resto della fase**

- Launcher nella shell del panel (`panel/src/App.jsx`), tema del panel rispettato (`theme.js`),
  testi in italiano, stati loading/error/empty espliciti.
- Il panel ha un bundler: importa `sdk/widget` dal workspace, non dal CDN. Stesso codice, un
  round-trip in meno e nessuna dipendenza dal CDN per una pagina autenticata.
- Origin del panel negli `allowed_origins` del nostro tenant, altrimenti `403` (§5 e §6).
- Escalation: apre una conversazione nella nostra inbox con l'email dell'operatore già
  compilata. È il modo in cui "assistenza ai nuovi utenti" diventa una cosa reale invece di uno
  slogan.
- Ciclo virtuoso già costruito: le domande a cui l'assistente non sa rispondere diventano gap
  sulla nostra knowledge base (`KnowledgeGapReview`, `KnowledgeDraft` esistono). La nostra
  documentazione migliora dalle domande vere dei clienti, senza scrivere codice nuovo.
- Ambito: `rag.py` ha già il guardiano dello scope. Con la nostra KB come corpus funziona da sé,
  ma il rifiuto fuori ambito va verificato **in tutte e sei le lingue**, come per il widget
  visitatore.

**Rate limit.** Tutto il panel passa dal nostro unico `client.id`, ma `chat_limiter` usa la
chiave `chat:{client_id}:{ip}`: gli utenti restano separati per IP. Con `chat_rate_limit` alto
(fase 0) non c'è collo di bottiglia. Da verificare con un test, non per deduzione.

## 9. Fase 6 — Pubblicazione e documentazione

- `@wp-aissistant/browser` su npm: pronto da tempo, bloccato solo su scope npm e `NPM_TOKEN`
  (procedura in `browser-sdk.md`).
- `@wp-aissistant/widget` come secondo pacchetto, stesso artefatto del CDN.
- `docs/embedded-widget.md` con opzioni, eventi, adapter host e nota SRI.
- `README.md` e `competitor-feature-backlog.md` aggiornati **nello stesso commit** della feature
  (regola 7).

## 10. Ordine, dipendenze e dimensione

```
Fase 0  tenant + piano interno            piccola   — sblocca 4 e 5
Fase 1  estrazione sdk/widget             grande    — il blocco vero
Fase 2  CDN (widget + zip del plugin)     media     — dipende da 1
Fase 3  installazione e configuratore     grande    — dipende da 1 e 2; contiene origin self-service
Fase 4  widget sul nostro sito            piccola   — dipende da 0 e 2
Fase 5  assistente nel panel              media     — dipende da 0 e 1 (non da 2 né da 3)
Fase 6  npm + docs                        piccola   — dipende da 1
```

La fase 5 **non** dipende dal CDN né dal configuratore: il panel importa `sdk/widget` dal
workspace e usa la nostra configurazione, non quella di un cliente. Se il CDN o il configuratore
si complicano, l'assistente nel panel può uscire prima.

La fase 3 è la più grande dopo l'estrazione, e vale la pena spacchettarla in due lock: prima
backend (`WidgetConfig`, endpoint, origin self-service e fail closed, vocabolario condiviso), poi
panel (scelta, configuratore, anteprima, snippet, download). Il primo pezzo è verificabile da
solo con i test tenant-scoped; il secondo senza il primo non esiste.

**Fasi 1 e 2 sono un unico treno di rilascio.** Da quando il plugin è uno shim, non può uscire
prima che il CDN esista: la versione 1.4.0 del plugin e la prima pubblicazione del widget si
rilasciano insieme, o i siti dei clienti restano senza widget. Vale anche al contrario — il
plugin va rilasciato con la versione **immutabile** già pubblicata e con SRI, non con l'alias
mobile.

**La licenza per dominio è indipendente e va iniziata subito.** `ClientOrigin`, `Plan.max_origins`
e soprattutto la **fase di osservazione** (§5) non dipendono da nessun'altra fase, e l'
osservazione ha un tempo di maturazione che non si comprime: più presto inizia a raccogliere
domini, più presto si può applicare senza spegnere il widget a qualcuno. È il primo blocco da
prendere, prima ancora della fase 0.

```
Licenza  osservazione → backfill → conferma → preavviso → applicazione
         ↑ da avviare subito, matura nel tempo, non blocca nient'altro
```

## 11. Rischi da tenere d'occhio

1. **Due widget invece di uno.** È il rischio che la fase 1 esiste per evitare. Se per fretta si
   costruisce un widget nuovo lasciando quello del plugin, da quel giorno ogni correzione si fa
   due volte e una delle due si dimentica.
2. **Spegnere clienti passando a fail closed.** Ridimensionato dopo la verifica in produzione
   (§5): la CORS stretta ferma già al preflight il traffico browser dai domini non ammessi,
   quindi la platea a rischio è la coda — chi passa grazie a un origin registrato da un altro
   tenant e chi usa il widget da un server. Resta il motivo per cui osservazione, backfill,
   conferma e preavviso vengono prima dell'applicazione, ma la data si decide su una query, non
   su una paura.
3. ~~**Il `403` silenzioso sull'origin.**~~ **Disinnescato** per il plugin: il widget scrive il
   motivo in console e il pannello ha la schermata dei domini (§5). Torna vivo con il widget
   standalone, che quel codice non ce l'ha ancora: va portato con l'estrazione della fase 1, non
   dopo — è il fallimento più probabile in installazione, e si manifesta come "il widget non c'è".
4. **Contesto tenant troppo generoso.** Un blocco di contesto che cresce a ogni richiesta di
   feature finisce per mettere dati di un cliente nel prompt di un modello. Whitelist, e la
   whitelist si allarga con una decisione esplicita.
5. **Il nostro tenant nelle statistiche commerciali.** Se non lo escludiamo prima di accendere
   il widget, le viste *Costi e margine* e *Crescita* diventano inaffidabili proprio mentre
   iniziamo a fidarcene.
6. **Piano Illimitato assegnato per errore.** `default_plan_id()` sceglie per id: oggi va bene,
   ma senza un test un riordino dei piani regala il piano illimitato a ogni nuovo iscritto.
7. **Il vocabolario delle opzioni che si triplica.** JavaScript, Python e PHP che descrivono le
   stesse 24 opzioni con tre liste scritte a mano è il debito 5 daccapo, e si manifesta come
   un'opzione che il panel offre e il widget ignora — senza errori da nessuna parte. Una
   dichiarazione sola e un test che confronta le copie generate.
8. **Configurazione in due posti per i clienti WordPress.** Dalla fase 3 il panel e la pagina
   del plugin configurano le stesse cose. Il formato ormai è identico — entrambi producono lo
   stesso oggetto di opzioni — ma resta da scegliere quale delle due vince, o il supporto non sa
   quale dei due sta guardando il cliente.
9. **Credere che il CDN protegga dalle manomissioni.** Non lo fa (§4), e il danno non è il CDN:
   è rinunciare ai controlli veri perché sembrano già coperti. Il binding origin che fallisce
   aperto va chiuso a prescindere da dove è ospitato il file.
10. **Un deploy sbagliato che rompe tutti i clienti insieme.** È il rischio nuovo introdotto dal
   CDN-first, e non esisteva quando il widget viveva dentro ogni sito. Versioni immutabili come
   default, alias mobile come scelta esplicita, rilascio a scaglioni, copia di riserva nel
   plugin.
11. **Clienti fermi su un plugin vecchio.** Fuori da WordPress.org gli aggiornamenti del PHP
    non arrivano da soli: senza un update server il parco si frammenta su versioni diverse dello
    shim e dell'adapter WooCommerce, e ogni diagnosi di supporto parte da "che versione hai?".
12. **Lo slot di staging che diventa un secondo sito gratis.** Due modi di sbagliarlo, entrambi
    silenziosi (§5): il confronto della parola chiave fatto per **sottostringa** invece che per
    etichetta DNS regala lo slot a chiunque abbia un dominio tipo `devoto.it`; e la parola chiave
    **senza il vincolo di sottodominio del live** non lega lo slot al cliente — `demo.altrosito.it`
    rispetta la convenzione ed è un secondo sito commerciale.
13. **Il cliente onesto che cambia dominio.** Rebrand, migrazioni e il passaggio da staging a
    live al lancio sono normali. Uno slot unico senza cambio self-service (§5) trasforma ogni
    migrazione in un ticket e punisce gli onesti più dei parassiti.

## 12. Prima di iniziare

Ogni blocco ha il suo lock in `docs/work-locks/active/`, pubblicato su `main` con un commit
dedicato prima di toccare il codice. Il blocco **licenza per dominio** tocca `backend/app/deps.py`,
`db.py`, `cors.py` e una migrazione; la fase 1 `wp-plugin/` e `sdk/`; la 2 e la 4 `website/`, il
CDN e la CI; la 3 `backend/` e `panel/`; la 5 `panel/` e `backend/`.

Attenzione a due sovrapposizioni: **licenza e fase 3** si contendono gli endpoint sugli origin,
e **fasi 3 e 5** si contendono `panel/` e `backend/`. Non vanno prese in parallelo con Codex a
meno che i lock non scendano al singolo file. Le altre sono perimetri disgiunti.
