---
block: eu-ai-inference
owner: codex
started_at: 2026-08-09T11:30:00+02:00
expires_at: 2026-08-11T11:30:00+02:00
branch: main
---

Obiettivo: rendere verificabile e fail-closed la configurazione di chat ed embedding con
inferenza regionale UE, predisponendo Mistral EU senza cambiare provider live senza benchmark.

Perimetro previsto:
- `backend/app/llm.py`
- `backend/app/production_config.py`
- test LLM/configurazione production pertinenti
- `backend/.env.example`
- `README.md`
- `docs/gdpr-eu-residency-audit.md`
- documento di migrazione/benchmark AI UE

Fuori perimetro:
- cancellazione post-disdetta e retention
- piani e billing
- panel e plugin
- creazione account/provider o inserimento di credenziali non disponibili
