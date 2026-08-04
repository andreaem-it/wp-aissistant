---
block: sdk-npm-publishing
owner: claude
started_at: 2026-08-04T22:03:11+02:00
expires_at: 2026-08-05T22:03:11+02:00
branch: worktree-sdk-npm-publishing
---

Obiettivo: rendere `@wp-aissistant/browser` pubblicabile su npm — metadati del pacchetto,
tipi TypeScript, README del pacchetto, licenza, verifica del contenuto del tarball in CI e
workflow di pubblicazione con provenance. Nessuna modifica al backend, al panel o al plugin.

Perimetro previsto:
- `sdk/browser/package.json`
- `sdk/browser/README.md`
- `sdk/browser/LICENSE`
- `sdk/browser/src/index.d.ts`
- `sdk/browser/src/widget.d.ts`
- `sdk/browser/test/package.test.js`
- `.github/workflows/ci.yml` (solo il job `browser-sdk`)
- `.github/workflows/publish-sdk.yml`
- `docs/browser-sdk.md`

Fuori perimetro:
- `backend/` per intero (incluso `main.py`, `db.py`, migrazioni e test)
- `panel/`
- `wp-plugin/` e widget WordPress
- `docs/competitor-feature-backlog.md` e `docs/handoff.md`: sono nel perimetro del lock
  `kb-gap-article-drafts`, la riga «SDK/widget headless» va aggiornata da chi chiude quel lock
  o da me dopo il suo rilascio.
