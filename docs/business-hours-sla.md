# SLA e orari lavorativi

Il calendario di supporto è configurabile dal panel in **Configurazione → Orari di supporto**.
Quando è attivo, le finestre di prima risposta e risoluzione avanzano soltanto durante i giorni e
gli orari selezionati. Un’escalation serale, nel weekend o durante la parte chiusa di un turno
notturno riparte dalla successiva apertura.

Il calcolo avviene nel backend, non nel browser, ed è tenant-scoped. Usa fusi IANA come
`Europe/Rome` e converte ogni intervallo in UTC, quindi gestisce automaticamente ora legale,
ora solare e turni che attraversano la mezzanotte. La modifica del calendario ricalcola anche le
conversazioni aperte con uno SLA già attivo.

Il plugin WordPress conosce già il fuso configurato in **Impostazioni generali**. La fondazione
backend conserva il campo `source` per distinguere configurazioni manuali e WordPress; il passo
successivo è una registrazione autenticata del sito che permetta al plugin di sincronizzare il
calendario senza rendere mutabile la configurazione tramite la chiave pubblica del widget.
