---
block: widget-on-our-site
owner: claude
started_at: 2026-08-13T03:00:00+02:00
expires_at: 2026-08-15T03:00:00+02:00
branch: main
---

Obiettivo: il widget sul nostro sito, con una knowledge base che gli permetta di rispondere.
Fase 4 di `docs/embedded-assistant-roadmap.md`.

Diventiamo utenti del nostro prodotto: l'escalation dal sito arriva nella **nostra** inbox, ed è
il primo uso del help desk dall'altra parte del banco.

La parte che non è "incollare uno snippet": senza contenuti indicizzati l'assistente risponde
«non lo so» a tutto, e su un sito che vende un assistente è la dimostrazione peggiore possibile.
La knowledge base va popolata con ciò che un potenziale cliente chiede — cosa fa il prodotto,
quanto costa, come si installa — e **non** con la documentazione interna: un README finito nel
retrieval risponderebbe a un prospect con dettagli d'implementazione.

Perimetro previsto:
- `website/index.html` (snippet), `website/_headers` (CSP)
- `docs/embedded-assistant-roadmap.md`, `docs/competitor-feature-backlog.md`, `README.md`

Fuori perimetro (liberi per un altro agente):
- `backend/`, `panel/`, `wp-plugin/`, `sdk/`, `cloudflare/`
- L'assistente dentro il pannello (fase 5)

Nota sulla CSP: il sito carica Font Awesome da cdnjs e i font da Google. Una CSP che li dimentica
rompe il sito invece di proteggerlo, ed è un guasto visibile su una pagina di vendita.
