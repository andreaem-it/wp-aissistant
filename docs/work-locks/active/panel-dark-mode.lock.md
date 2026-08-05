---
block: panel-dark-mode
owner: claude
started_at: 2026-08-05T23:10:00+02:00
expires_at: 2026-08-06T23:10:00+02:00
branch: main
---

Obiettivo: tema scuro del panel operatore e superadmin, con i tre stati già usati dal widget
(chiaro / scuro / automatico dal sistema), preferenza persistente e contrasto verificato.

Perimetro previsto:
- `panel/src/index.css` — set di token scuri e tokenizzazione dei colori ancora cablati
- `panel/src/theme.js` e `panel/src/theme.test.js` (nuovi)
- `panel/src/App.jsx`, `panel/src/Admin.jsx`, `panel/src/main.jsx` — selettore e applicazione
- `README.md`

Fuori perimetro:
- backend e migrazioni: la preferenza resta locale al browser, non va nel database
- widget e plugin WordPress (hanno già il proprio tema)
- sito marketing
- qualsiasi logica di prodotto: qui si tocca solo presentazione
