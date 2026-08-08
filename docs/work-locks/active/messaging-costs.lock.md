# Lock: costi di email e canali nel margine (debito 4)

**Area**: `backend/app/usage.py` (nuovo), `db.py`, `costs.py`, `email.py`, `whatsapp.py`,
`alembic/`, `panel/src` (Costi e margine)
**Aperto**: 2026-08-08

Il margine conta inferenza, embedding e storage. Restano fuori le email transazionali e i
messaggi sui canali: oggi non sono nemmeno rilevati, quindi va creata la registrazione.

Confine di attribuzione: sono costo del tenant le email generate dal suo traffico (risposta al
visitatore, canale email, azione di workflow). Verifica indirizzo, reset password e avvisi di
fatturazione sono spesa di piattaforma e restano fuori, dichiarate.
