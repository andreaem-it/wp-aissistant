---
block: admin-origin-kinds
owner: claude
started_at: 2026-08-13T02:10:00+02:00
expires_at: 2026-08-14T02:10:00+02:00
branch: main
---

Obiettivo: l'endpoint admin sui domini smette di dire «il primo è live, tutti gli altri sono
staging» e assegna **live finché il piano lo consente**, poi staging.

Il caso che lo rende necessario, trovato provando a creare il nostro tenant: `wpaissistant.it` e
`panel.wpaissistant.it` sono due siti di produzione, non un sito e il suo staging — `panel` non è
un'etichetta di sviluppo, e giustamente la validazione lo rifiuta. Il piano interno concede
domini illimitati, quindi il modello lo permette: era solo la convenzione dell'endpoint a non
saperlo esprimere.

Perimetro previsto:
- `backend/app/origins.py` (assegnazione condivisa)
- `backend/app/routers/admin.py` (`create_client`, `set_client_origins`)
- `backend/tests/test_origins.py`

Fuori perimetro: tutto il resto.
