---
block: grounding-prompt-fix
owner: claude
started_at: 2026-08-08T09:00:00+02:00
expires_at: 2026-08-09T09:00:00+02:00
branch: main
---

Obiettivo: togliere dal prompt lo strumento inesistente `escalate_to_human` e rendere esplicito
il divieto di rispondere fuori dal contesto. Il modello riceveva due istruzioni contraddittorie
sull'escalation e, non potendo eseguire quella sbagliata, rispondeva comunque inventando.

Perimetro previsto:
- `backend/app/rag.py` (`build_system`)
- `backend/tests/test_scope_guard.py` o nuovo test sul prompt
- `docs/handoff.md` se serve

Fuori perimetro:
- sincronizzazione delle impostazioni WooCommerce: blocco successivo
- soglia di scope, retrieval, reranking: non si toccano senza i dati del debug
