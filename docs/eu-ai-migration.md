# Migrazione dell'inferenza AI in UE

## Decisione

Cloudflare Workers AI non supporta Regional Services e non fornisce oggi la garanzia richiesta
per affermare che prompt, risposte ed embedding siano elaborati esclusivamente nell'UE.

Il candidato primario è l'endpoint regionale Mistral `https://api.eu.mistral.ai/v1`: la
documentazione del provider dichiara inferenza in data center UE/EFTA e dati elaborati senza
uscire dalla regione. Mistral è inoltre supportato da LiteLLM e `mistral-embed` produce vettori
da 1024 dimensioni, compatibili con lo schema attuale.

Fonte primaria: [Mistral Regional Inference](https://docs.mistral.ai/studio-api/regional-inference).

## Configurazione candidata

```env
CHAT_MODEL=mistral/mistral-small-latest
EMBED_MODEL=mistral/mistral-embed
EMBED_DIM=1024
LLM_API_BASE=https://api.eu.mistral.ai/v1
MISTRAL_API_KEY=<secret>
REQUIRE_EU_AI=true
STRICT_PRODUCTION_CONFIG=true
```

`REQUIRE_EU_AI` è un vincolo fail-closed: rifiuta l'avvio se endpoint, modelli o credenziale
non corrispondono al percorso regionale approvato. Non è un semplice badge nel panel.

## Benchmark obbligatorio

Non cambiare le variabili live prima di aver eseguito, sullo stesso dataset tenant:

1. retrieval recall@k e MRR dopo re-embedding Mistral;
2. answer quality, groundedness e blocco fuori ambito;
3. escalation, lookup ordine e marker deterministici;
4. italiano: tono, precisione su WooCommerce e resistenza alle allucinazioni;
5. latenza p50/p95 e tasso errori su chat normale e streaming;
6. costo per conversazione e per milione di caratteri ingeriti;
7. test di cancellazione/logging e verifica contrattuale DPA/subprocessori.

Soglia go/no-go proposta: nessuna regressione sui test di sicurezza e commerce, groundedness
non inferiore alla baseline, recall@k non inferiore di oltre 2 punti percentuali, p95 entro il
20% della baseline o miglioramento di costo che giustifichi la differenza.

## Rollout

1. Creare account e sottoscrivere DPA Mistral; generare una chiave dedicata production.
2. Eseguire benchmark offline senza modificare il database live.
3. Preparare una nuova colonna/vector index solo se la dimensione effettiva differisce da 1024.
4. Re-embed della knowledge base con job idempotenti, mantenendo i vecchi chunk finché i nuovi
   non sono completi.
5. Canary su un tenant interno, poi 10%, 50%, 100%, con rollback immediato a ogni regressione.
6. Impostare `REQUIRE_EU_AI=true` solo al passaggio definitivo e archiviare evidenza di endpoint,
   contratto, regione e test.

## Stato

- Guardrail applicativo e documentazione: implementati.
- Account, DPA e chiave Mistral: mancanti.
- Benchmark comparativo: da eseguire.
- Migrazione live: non autorizzata finché i punti precedenti non sono chiusi.
