---
block: internal-tenant-plan
owner: claude
started_at: 2026-08-12T16:10:00+02:00
expires_at: 2026-08-15T16:10:00+02:00
branch: main
---

Obiettivo: il piano **interno illimitato** e il nostro tenant, con le viste commerciali che non
si lasciano falsare da un cliente che non paga perché siamo noi. È la fase 0 di
`docs/embedded-assistant-roadmap.md`: senza un nostro tenant non c'è widget sul nostro sito né
dentro il pannello dei clienti.

Il punto meno ovvio, e la ragione per cui il blocco non è solo una migrazione: il nostro tenant
genererà costo di inferenza, embedding e storage con ricavo zero. Senza escluderlo, in *Costi e
margine* comparirebbe come il cliente più in perdita del parco e nel funnel di attivazione come
un cliente vero con numeri fuori scala — cioè renderebbe inaffidabili le viste appena costruite,
proprio mentre iniziamo a fidarcene. La sua spesa va dichiarata separatamente come **costo di
piattaforma**, mai contata come gratis: è la stessa regola già in vigore per i canali non
prezzati.

Perimetro previsto:
- `backend/alembic/versions/0055_*.py` (il piano interno illimitato)
- `backend/app/db.py` (docstring di `Plan.internal`: oggi dice che non concede nulla)
- `backend/app/billing.py` (`internal_client_ids`, esclusione dai ricavi)
- `backend/app/costs.py` (spesa dei tenant interni separata, non nel margine)
- `backend/app/growth.py` (funnel e clienti a rischio senza i tenant interni)
- `backend/tests/test_plans.py`, `test_costs.py`, `test_growth.py`, `test_billing.py`
- `panel/src/Admin.jsx` (l'etichetta «segnaposto» non vale più per tutti i piani interni)
- `README.md`, `docs/competitor-feature-backlog.md`, `docs/embedded-assistant-roadmap.md`

Fuori perimetro (liberi per un altro agente):
- `wp-plugin/`, `sdk/`, `website/`, `cloudflare/`
- Il widget sul nostro sito e dentro il pannello (fasi 4 e 5 della roadmap): questo blocco
  prepara il tenant, non lo usa
- L'estrazione del widget in `sdk/widget` (fase 1)
- La creazione del nostro tenant in produzione, che è un'operazione sui dati e va fatta a mano
  dopo il rilascio
