# Lock: il guardiano di scope ignora il catalogo

**Area**: `backend/app/routers/widget.py`, `backend/app/rag.py`
**Aperto**: 2026-08-07

Il guardiano di scope decide su soli chunk di testo. Un prodotto a catalogo che corrisponde
alla domanda non conta come prova di pertinenza, quindi "avete la felpa con zip?" può uscire
"fuori ambito" — e quel percorso risponde con `products: []`, card comprese.

Correzione: una corrispondenza di prodotto sotto `PRODUCT_MAX_DISTANCE` (0.45, più severa di
`SCOPE_MAX_DISTANCE` = 0.62) rende la domanda in ambito.
