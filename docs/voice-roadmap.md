# WP AIssistant — Voice System · Roadmap di progetto

> Stato: **proposta / progetto**. Non ancora in sviluppo. Documento vivo, da iterare.
> Data: 2026-07-27.

Obiettivo: gestire le **chiamate telefoniche** allo stesso modo in cui oggi gestiamo la chat.
Il cliente chiama un numero, parla con l'assistente AI (che risponde usando la knowledge base
del sito), e quando serve un umano la chiamata viene passata a un operatore — esattamente come
l'escalation della chat, ma in voce.

È un'integrazione lunga e potenzialmente **trasformativa** per il prodotto (da "chat widget" a
"customer-support AI omnicanale"). Va affrontata a fasi, con un PoC che validi la latenza prima
di investire.

---

## 1. Principio architetturale: "stesso cervello, nuove orecchie e bocca"

Il valore che abbiamo già costruito è il **cervello**: RAG sui contenuti del sito, escalation a
3 vie, ticketing, order-lookup, knowledge base per-cliente, quote, osservabilità. Tutto questo
**si riusa quasi invariato**. La voce aggiunge solo:

```
  Telefono (PSTN)                                   ┌─────────────────────────────┐
        │                                           │   BACKEND ESISTENTE          │
        ▼                                           │   (il "cervello")            │
  ┌───────────────┐   audio    ┌──────────────┐     │                             │
  │  Telefonia    │◀──────────▶│  Voice Agent │◀───▶│  RAG / retrieve             │
  │  (numero,     │  realtime  │  Runtime     │ HTTP│  answer + escalation logic  │
  │   SIP/Twilio) │            │  (STT→LLM→TTS)│    │  order-lookup               │
  └───────────────┘            └──────────────┘     │  ticketing / conversazioni  │
        │                              │            │  knowledge base / multi-tenant│
        │  transfer a operatore        │            └─────────────────────────────┘
        ▼                              ▼                          ▲
   Operatore umano            Panel (trascrizione,               │
   (warm transfer)             live monitor, call ticket) ───────┘
```

**Decisione chiave: pipeline a cascata, non speech-to-speech puro.**
Per riusare il RAG testuale esistente scegliamo la pipeline **STT → LLM(testo)+RAG → TTS**
invece di un modello audio-to-audio puro. Motivi:
- il grounding RAG (rispondi solo dal contesto) e i marcatori `ESCALATE:` / `ORDER_LOOKUP:`
  vivono già nel mondo testuale: riusarli è immediato;
- controllo pieno su cosa dice l'AI (critico per dati d'ordine, rimborsi, ecc.);
- indipendenza dal provider LLM (resta via LiteLLM).

Costo: latenza leggermente superiore al S2S puro. Si mitiga con **streaming end-to-end**
(STT parziale in streaming → LLM in streaming → TTS in streaming) e barge-in (l'utente può
interrompere l'AI). Target latenza percepita: **< 1s** dal fine-parlato alla prima sillaba.

---

## 2. Build vs Platform (la scelta più importante)

Il layer realtime (audio bidirezionale, barge-in, turn-taking, telefonia) è la parte
genuinamente **difficile**. Tre approcci:

| Approccio | Cosa | Pro | Contro |
|-----------|------|-----|--------|
| **A. Platform gestita** (es. Vapi, Retell, Bland) | Danno numero + pipeline realtime pronta; noi esponiamo il "cervello" come webhook/tool | PoC in giorni, latenza risolta | Costo per-minuto, meno controllo, lock-in |
| **B. Framework realtime self-host** (es. LiveKit Agents, Pipecat) | Orchestrazione open-source; noi colleghiamo STT/LLM/TTS + telefonia (SIP/Twilio) | Controllo, self-host, costi trasparenti | Più lavoro infra, gestione realtime |
| **C. Fai-da-te** (Twilio Media Streams + STT + TTS + glue) | Tutto a mano | Massimo controllo | Massimo sforzo, latenza tosta da domare |

**Raccomandazione**: **Fase PoC su (A) o (B)** per validare latenza/UX senza costruire l'infra
realtime da zero; il "cervello" resta nel nostro backend (esposto come tool/webhook). Dopo il
PoC, decidere se consolidare su (B) self-host per controllo e margini, o restare su (A) per
time-to-market. **Non partire da (C).**

Componenti tipici (indipendenti dal provider): **STT** (es. Deepgram/Whisper streaming),
**LLM** (il nostro, via LiteLLM), **TTS** (es. ElevenLabs/Cartesia, bassa latenza),
**telefonia** (Twilio/Telnyx per numeri + SIP).

---

## 3. Cosa si riusa vs cosa è nuovo

**Si riusa (poco/nessun lavoro):**
- Retrieval RAG (`rag.py`), prompt di sistema, marcatori `ESCALATE:`/`ORDER_LOOKUP:`.
- Ticketing, modello `Conversation`/`Message`, order-lookup, knowledge base, multi-tenant.
- Osservabilità (`AiResponseLog`), quote (adattate a minuti/chiamate).

**Nuovo:**
- Layer telefonia + runtime voce realtime (STT/TTS/turn-taking/barge-in).
- **Numero di telefono per-cliente** e instradamento al giusto tenant.
- **Handoff vocale**: warm transfer verso il telefono/panel dell'operatore, oppure
  messaggio+callback se nessun operatore è disponibile.
- Trascrizione realtime + registrazione + consenso.
- Viste "chiamate" nel panel (live, storico, ticket da chiamata).
- Impostazioni voce per-cliente (lingua, voce TTS, saluto, orari, fallback).
- Billing a **minuti/chiamate** (nuovo asse di quota) + pass-through costi telefonia.

---

## 4. Modello dati (aggiunte previste)

- `PhoneNumber` — numero E.164 ↔ `client_id` (routing del tenant), stato, provider.
- `Call` — `client_id`, `direction` (inbound/outbound), `from`/`to`, `status`
  (ringing/active/transferred/completed/missed), `started_at`/`ended_at`, `duration_s`,
  `recording_url`, `outcome` (answered_ai/escalated/voicemail/callback), collegata a una
  `Conversation` (così la trascrizione riusa `Message`).
- `CallEvent`/segmenti — trascrizione con timestamp e ruolo (caller/ai/operator), barge-in.
- Estensioni `Client`: `voice_enabled`, `voice_lang`, `voice_id` (TTS), `voice_greeting`,
  `business_hours`, `transfer_target` (numero/coda operatore).
- Estensioni `Plan`: quota **minuti/mese** o **chiamate/mese** (oltre ai messaggi chat).

La trascrizione della chiamata è a tutti gli effetti una `Conversation` di canale `voice`:
il panel, i ticket, l'order-lookup e le statistiche funzionano già.

---

## 5. Roadmap a fasi

### Fase 0 — Spike / PoC tecnico (validazione latenza)  ·  *rischio: alto*
- Un solo numero, una lingua, inbound.
- Pipeline minima: STT streaming → chiamata al nostro endpoint `/chat` (o nuovo `/voice/turn`)
  → TTS streaming. Nessuna escalation, nessun DB.
- **Domanda a cui rispondere**: la latenza percepita è accettabile (< ~1s) con la cascata +
  il nostro RAG? Barge-in funziona? Qualità voce/lingua IT sufficiente?
- Deliverable: una demo chiamabile + numeri di latenza reali. **Go/No-go** sull'approccio.

### Fase 1 — MVP voce (l'AI risponde al telefono)  ·  
- Endpoint backend dedicato `/voice/turn` (o riuso di `/chat` con `channel=voice`): stesso RAG,
  ma **prompt e formato ottimizzati per la voce** (risposte brevi, niente markdown/URL letti male,
  gestione numeri/ortografia parlata).
- Routing numero → tenant (`PhoneNumber`). Impostazioni voce per-cliente (lingua, voce, saluto).
- La chiamata crea una `Conversation` canale `voice`; ogni turno logga in `AiResponseLog`.
- Fine chiamata: trascrizione salvata, `Call` chiuso con esito.
- Deliverable: un cliente pilota può ricevere chiamate gestite dall'AI, visibili nel panel come
  trascrizione.

### Fase 2 — Escalation & handoff umano  ·  *il cuore del "come la chat"*
- Marcatore `ESCALATE:` in voce ⇒ due strategie:
  - **Warm transfer**: trasferisci la chiamata a un operatore (numero/coda), passandogli il
    contesto (schermata panel con trascrizione live).
  - **Nessun operatore disponibile** (fuori orario/occupato): prendi un **messaggio/callback**,
    apri un **ticket** con la trascrizione + il recapito. Riusa notifiche email/webhook esistenti.
- Keyword d'escalation vocali (rimborso/reclamo/operatore…) + decisione del modello.
- Deliverable: la telefonata sa passare a un umano o raccogliere un callback, con ticket.

### Fase 3 — Identità & order-lookup in voce
- Order-lookup via voce: numero d'ordine via **DTMF** (tastiera) o parlato + verifica identità
  (email/cognome), riusando la logica a livelli già esistente (`ORDER_LOOKUP:`).
- Gestione robusta di numeri/codici a voce (conferma, ripetizione, spelling).
- Deliverable: "dov'è il mio ordine?" al telefono funziona come in chat.

### Fase 4 — Esperienza operatore nel panel
- Vista **Chiamate**: live (trascrizione in tempo reale, listen-in/whisper), storico con
  **registrazioni** e trascrizioni ricercabili, ticket da chiamata.
- Trasferimento/gestione coda dal panel; presenza operatori (disponibile/occupato).
- Statistiche voce (chiamate/giorno, % gestite da AI, durata media, tasso transfer, orari picco).
- Deliverable: l'operatore lavora le chiamate come oggi lavora chat e ticket.

### Fase 5 — Outbound & avanzato
- Callback automatici (l'AI richiama), reminder, conferme.
- IVR/menu iniziale opzionale, voicemail, instradamento per reparto.
- Deliverable: non solo inbound reattivo ma flussi proattivi.

### Fase 6 — Scala, billing, compliance
- **Quote a minuti/chiamate** per piano + enforcement (come le quote messaggi) + pass-through
  dei costi telefonia; pagine prezzi/sito aggiornate (canale voce).
- **Compliance**: consenso alla registrazione (annuncio inizio chiamata), retention/cancellazione
  registrazioni (GDPR), regolamenti telefonici per-paese, STIR/SHAKEN per l'outbound, gestione
  numeri e portabilità.
- Multi-region/latency, failover, osservabilità voce (metriche latenza pipeline).

---

## 6. Preoccupazioni trasversali (da tenere d'occhio dall'inizio)

- **Latenza**: è il make-or-break. Budget indicativo: STT ~150–300ms, LLM primo token ~300–500ms,
  TTS primo audio ~150–300ms → serve streaming ovunque e barge-in.
- **Costo**: voce = telefonia + STT + TTS + LLM per minuto. Va modellato **prima** di prezzare:
  la quota "messaggi" non basta, serve "minuti/chiamate". Rischio di erodere margini se non
  tracciato (stesso principio delle quote messaggi).
- **Compliance/legale**: consenso registrazione, GDPR sulle registrazioni vocali (dato biometrico
  in alcune interpretazioni), regole telefoniche per-paese, do-not-call per l'outbound.
- **Qualità voce & lingua**: TTS naturale in IT (e multilingua), gestione accenti/rumore su STT.
- **Sicurezza**: isolamento per-tenant del routing numeri, anti-fraud (toll fraud sull'outbound),
  protezione dati d'ordine come già fatto in chat.
- **Prompt "voice-first"**: le risposte vanno riscritte per l'orecchio (brevi, niente elenchi
  lunghi, niente URL/markdown letti ad alta voce, conferme esplicite sui dati).
- **Fallback**: cosa succede se STT/TTS/LLM è lento o giù? Messaggio di cortesia + transfer/callback.

---

## 7. Rischi & incognite principali

1. **Latenza della cascata + RAG**: da validare in Fase 0. Se insufficiente, valutare un
   modello realtime speech-to-speech per il turn-taking, mantenendo il RAG via function-calling
   (più complesso, meno controllo).
2. **Warm transfer**: integrazione telefonia ↔ operatori (numeri/soft-phone/coda) è non banale.
3. **Costi a volume**: la voce costa molto più della chat per interazione; il modello di prezzo
   va ripensato.
4. **Compliance registrazioni**: può bloccare la vendita in alcuni mercati se non gestita.

---

## 8. Sequenza consigliata

**Prima**: Fase 0 (PoC latenza, go/no-go) → Fase 1 (MVP inbound) → Fase 2 (escalation, il vero
"come la chat"). Queste tre danno un prodotto voce vendibile in beta.
**Poi**: Fase 3 (order-lookup voce) e Fase 4 (panel operatore) in parallelo.
**Infine**: Fase 5–6 (outbound, billing, compliance) prima del GA.

Nessuna di queste fasi va iniziata finché la Fase 0 non conferma che la latenza regge: è
l'unico vero rischio tecnico bloccante.
