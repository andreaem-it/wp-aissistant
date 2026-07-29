# Security review — WooCommerce order lookup (2026-07-27)

Review della feature "lookup ordini in chat" (plugin `wpai/v1/order-lookup` + backend
`_order_lookup`/`_detect_order_lookup`). Tocca dati d'ordine e verifica d'identità → area
sensibile.

## Findings & stato

### 🔴 F1 — Token identità falsificabile (RISOLTO)
Il `user_token` che sblocca i **dati completi** dell'ordine (indirizzo, articoli, totale) era
firmato in HMAC con l'**`api_key`**. L'api_key è **pubblica**: viene localizzata nel JS del
widget (`WPAI.apiKey`), quindi leggibile da chiunque nel sorgente della pagina. Un attaccante
poteva forgiare un token valido con un `user_id` arbitrario e ottenere i dati completi di
ordini altrui.
**Fix**: token firmato con `wp_salt('auth')` (segreto server-side, `wpai_token_secret()`),
mai esposto al browser. Plugin v0.9.1.

### 🟠 F2 — SSRF via `site_url` (RISOLTO)
Il backend costruiva l'URL di callback da `site_url` (body param **controllabile
dall'attaccante**) senza validarlo → poteva essere indotto a fare POST verso URL interni
(es. metadata cloud) o arbitrari, con l'api_key nell'header.
**Fix**: `_trusted_callback_origin()` valida l'origine scelta contro gli `allowed_origins` del
client; se nessuna origine è fidata restituisce "" e il lookup fallisce con messaggio generico
(nessuna richiesta a host non fidati). **Conseguenza**: il lookup ordini ora **richiede
`allowed_origins` configurato** per il client.

### 🟡 F3 — Rotta REST auth con api_key pubblica + no rate-limit (APERTO, basso dopo F1/F2)
`POST /wp-json/wpai/v1/order-lookup` è autenticata con l'api_key (pubblica), quindi chiamabile
direttamente da chiunque, senza rate-limit. Dopo F1 (token non falsificabile) l'esposizione è
limitata al **tier base** (stato + data spedizione) e richiede comunque un `identifier`
(email/cognome) che **combaci** con l'ordine. Rischio residuo: enumerazione degli ordini di una
persona di cui si conosce il cognome, iterando i numeri d'ordine.
**Raccomandazione**: introdurre un **segreto server-to-server dedicato** tra backend e plugin
(diverso dall'api_key pubblica) per autenticare la rotta, ed eventualmente un rate-limit
sui *fallimenti* di verifica per IP. Non fatto in questa iterazione (richiede provisioning di
un secret per-client condiviso).

## Note minori
- Confronto `strcasecmp` sull'identifier non è constant-time (timing) — impatto trascurabile
  qui (valore specifico dell'ordine, controllato dall'attaccante).
- Le risposte d'ordine sono templata in modo deterministico lato backend (`_format_order_reply`),
  senza un secondo giro LLM → niente allucinazioni su dati finanziari. ✔️ buona scelta.

## Test
- `backend/tests/test_order_lookup_security.py`: il guard SSRF accetta solo origini in allowlist,
  rifiuta `site_url` spoofato, richiede allowlist configurata.
- F1 (token) è una fix PHP, coperta da review (non testabile nella suite pytest).
