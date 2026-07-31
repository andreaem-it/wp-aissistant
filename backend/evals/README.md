# RAG evaluation

La suite esegue lo stesso retrieval, MMR, soglie di scope e prompt usati in produzione,
senza creare conversazioni o ticket. Il dataset deve essere specifico per tenant perché i
`source_ref` dipendono dagli URL e dai documenti realmente sincronizzati.

## Dataset

Un caso JSON per riga:

- `id`, `query`, `expected_outcome` (`answer`, `out_of_scope`, `escalate`) sono obbligatori;
- `relevant_sources` contiene stringhe che devono comparire nei `source_ref` selezionati;
- `required_terms` e `forbidden_terms` verificano la risposta generata.

Copia `dataset.example.jsonl`, sostituisci le fonti e i contenuti con quelli del tenant e
mantieni almeno: domande rispondibili, parafrasi, richieste che richiedono autorità umana,
domande fuori ambito e small talk.

## Esecuzione

Dal percorso `backend/`, con le stesse variabili di database e provider AI della produzione:

```bash
python -m evals.rag_eval \
  --client-id 1 \
  --dataset evals/dataset.example.jsonl \
  --min-pass-rate 0.90 \
  --output rag-eval-report.json
```

Per verificare solo retrieval e scope guard senza chiamare il modello:

```bash
python -m evals.rag_eval --client-id 1 --dataset evals/dataset.example.jsonl --no-llm
```

Il comando restituisce exit code `1` quando il pass rate è inferiore alla soglia, quindi può
essere usato in CI dopo aver predisposto un database evaluation stabile. Il report include
pass rate, accuratezza dell'outcome, recall delle fonti attese e dettaglio di ogni caso.
