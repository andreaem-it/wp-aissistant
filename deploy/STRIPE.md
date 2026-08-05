# Attivare Stripe (checkout + webhook)

Il codice è già pronto: `/billing/checkout` e `/billing/webhook` restano disattivi finché non
imposti le chiavi. **Le chiavi vanno solo nelle env var di Railway — mai nel repo né in chat.**
Parti in **test mode**, poi ripeti in **live**.

## 1. Prodotto e prezzo su Stripe

1. Stripe Dashboard → attiva **Test mode** (toggle in alto).
2. **Product catalog → Add product**: nome (es. "Pro"), prezzo **ricorrente** (es. 79 €/mese).
3. Copia il **Price ID** (`price_…`) del prezzo creato. (Non è segreto.)

## 2. Collega il price id al piano

Con la tua `ADMIN_API_KEY`:

```bash
curl -X POST https://<tuo-dominio>/admin/plans/<plan_id> \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"stripe_price_id": "price_..."}'
```

(`GET /admin/plans` per gli id dei piani.)

## 3. Chiave segreta API

Stripe → **Developers → API keys** → copia la **Secret key** (`sk_test_…`).

## 4. Webhook

1. Stripe → **Developers → Webhooks → Add endpoint**.
2. URL: `https://<tuo-dominio>/billing/webhook`
3. Eventi da inviare:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `customer.subscription.trial_will_end` *(email di preavviso fine prova)*
   - `invoice.payment_failed` *(email di pagamento non riuscito)*
4. Dopo la creazione, copia il **Signing secret** (`whsec_…`).

## 5. Portale di fatturazione

`POST /billing/portal` apre il portale ospitato da Stripe: è lì che il cliente aggiorna la carta,
scarica le fatture, cambia piano e disdice, senza passare dal supporto.

1. Stripe → **Settings → Billing → Customer portal**.
2. Attiva le funzioni che vuoi concedere: metodo di pagamento, storico fatture, aggiornamento
   dell'abbonamento (elenca i price id consentiti) e cancellazione.
3. Imposta i link a termini e privacy: Stripe li richiede prima di poter salvare.

> Finché il portale non è configurato in dashboard, `/billing/portal` risponde `502`: il panel
> mostra "portale non raggiungibile" invece di una schermata rotta.

## 6. Env var su Railway (dashboard → Variables)

| Variabile | Valore |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_test_…` |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` |
| `BILLING_SUCCESS_URL` | es. `https://app.tuodominio.com/billing?status=success` |
| `BILLING_CANCEL_URL` | es. `https://app.tuodominio.com/billing?status=cancel` |
| `BILLING_PORTAL_RETURN_URL` | es. `https://app.tuodominio.com/billing` (default: `BILLING_SUCCESS_URL`) |

> Usa la **dashboard** di Railway, non la CLI in una sessione condivisa: eviti che la chiave
> finisca nei log. Dopo il salvataggio Railway ridistribuisce il backend.

## 7. Prova end-to-end (test mode)

1. Come operatore, avvia il checkout:
   ```bash
   curl -X POST https://<tuo-dominio>/billing/checkout \
     -H "Authorization: Bearer <token-operatore>" \
     -H "Content-Type: application/json" \
     -d '{"plan_id": <plan_id>}'
   # -> {"checkout_url": "https://checkout.stripe.com/..."}
   ```
2. Apri l'URL, paga con la **carta di test** `4242 4242 4242 4242`, scadenza futura, CVC qualsiasi.
3. Verifica: in Stripe → Webhooks l'evento risulta **consegnato (200)**; e il client ha
   `billing_status = active` e il `plan_id` aggiornato (`GET /admin/clients`).

## 8. Andare in live

Ripeti 1–6 con **Test mode OFF**: nuovi price id live, `sk_live_…`, nuovo webhook live con il
suo `whsec_…`, portale configurato anche in live. Aggiorna le env var di Railway.

## Registrazione self-service (signup)

Il sito e il panel hanno una **registrazione self-service** (`POST /signup`): l'utente sceglie
un piano, si apre Stripe Checkout in modalità subscription con **prova gratuita di `TRIAL_DAYS`
giorni** e **carta obbligatoria** (pre-autorizzata, addebito solo a fine prova). Perché funzioni:
il piano deve avere `stripe_price_id` impostato (passo 1-2) e le chiavi/webhook configurati.
Regola `TRIAL_DAYS` (default 14) tra le env di Railway.

## Cosa succede se un cliente non paga

- **`past_due`** (pagamento fallito, Stripe ritenta): nessun cambiamento — periodo di **grazia**,
  il cliente continua sul suo piano.
- **`canceled`** (abbonamento terminato): il client viene **retrocesso automaticamente al piano
  Free** (i limiti Free si applicano subito). Riabbonandosi torna sul piano scelto.

In entrambi i casi il cliente **viene avvisato**: gli operatori verificati del tenant ricevono
un'email, e nel panel compare un avviso con il pulsante per aprire il portale. Le email
richiedono SMTP configurato; se manca, il messaggio finisce nei log invece che nella casella.

## Sicurezza

- Non committare mai le chiavi; non incollarle in chat. Se una `sk_…` viene esposta, **ruotala**
  subito (Developers → API keys → Roll key).
- Il webhook è protetto dalla **verifica della firma** (`STRIPE_WEBHOOK_SECRET`): richieste non
  firmate correttamente ricevono `400`.
