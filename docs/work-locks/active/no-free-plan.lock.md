# Lock: nessun piano gratuito

**Area**: `panel/src/Admin.jsx`, `backend/app/routers/admin.py`, test dei piani
**Aperto**: 2026-08-09

Non esiste una versione gratuita del prodotto, ma il pannello scrive «Gratis» per ogni
prezzo a zero e il form di creazione lo suggerisce (`0 = gratis`).

La stessa `formatPrice` è la `money()` delle viste costi e ricavi: lì uno zero significa
zero euro, quindi un costo o un margine esattamente a zero compare come «Gratis».
