---
block: assistant-knows-its-subject
owner: claude
started_at: 2026-08-13T03:30:00+02:00
expires_at: 2026-08-14T03:30:00+02:00
branch: main
---

Obiettivo: l'assistente sa **come si chiama ciò di cui parla**.

Il prompt di grounding vieta di inventare prezzi, corrieri, tempi di consegna, nomi di pagina e
URL, ma non dà mai al modello il nome del tenant: dice solo «this specific shop». Finché le
domande riguardano prodotti e spedizioni non si nota. Quando il soggetto della domanda **è il
prodotto stesso** — «come si installa?» — il modello deve riempire quello slot e lo inventa.

Trovato sul nostro sito, provando la Fase 4: alla stessa domanda ha risposto tre volte con tre
soggetti diversi, uno dei quali era «dmap», un nome che non esiste. La risposta era per il resto
corretta, il che la rende peggiore: è plausibile.

Perimetro previsto:
- `backend/app/rag.py` (`build_system`)
- i chiamanti che le passano il contesto (`routers/widget.py`, `backend/evals`)
- `backend/tests/`

Fuori perimetro: `website/`, `panel/`, `wp-plugin/`, `sdk/`.
