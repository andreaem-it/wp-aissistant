# SLA e orari lavorativi

Il calendario di supporto è configurabile dal panel in **Configurazione → Orari di supporto**.
Quando è attivo, le finestre di prima risposta e risoluzione avanzano soltanto durante i giorni e
gli orari selezionati. Un’escalation serale, nel weekend o durante la parte chiusa di un turno
notturno riparte dalla successiva apertura.

Il calcolo avviene nel backend, non nel browser, ed è tenant-scoped. Usa fusi IANA come
`Europe/Rome` e converte ogni intervallo in UTC, quindi gestisce automaticamente ora legale,
ora solare e turni che attraversano la mezzanotte. La modifica del calendario ricalcola anche le
conversazioni aperte con uno SLA già attivo.

Il plugin WordPress sincronizza automaticamente giorni, fascia e valore restituito da
`wp_timezone_string()` quando vengono salvate le impostazioni del widget o cambia il fuso del sito.
Il backend accetta sia nomi IANA sia offset WordPress come `+02:00`.

La chiave del widget è pubblica e non autorizza la modifica diretta del calendario. Alla prima
sincronizzazione il backend verifica che il sito appartenga alle origini consentite, invia una
challenge casuale alla rotta REST `wpai/v1/site-proof` e controlla la prova HMAC. Solo allora
registra l’hash della credenziale privata generata dall’installazione. Le sincronizzazioni
successive usano quella credenziale server-side; il segreto non viene localizzato nel JavaScript.
