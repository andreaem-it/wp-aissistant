# Sito marketing su Cloudflare Pages

Il sito in `website/` è **statico** (nessun build): `index.html` + `styles.css` + `_headers`.
Due modi per pubblicarlo su Cloudflare Pages — scegline uno.

## Opzione A — Git integration (consigliata, zero config nel repo)

Cloudflare builda e deploya da solo a ogni push, con preview automatiche sui PR.

1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**.
2. Seleziona il repo `andreaem-it/wp-aissistant`.
3. Build settings:
   - **Framework preset:** None
   - **Build command:** *(vuoto)*
   - **Build output directory:** `website`
   - **Root directory:** *(lascia la root)*
4. Deploy. Otterrai un dominio `https://<project>.pages.dev`.
5. (Opzionale) **Custom domain**: Pages → Custom domains → aggiungi es. `www.tuodominio.com`
   (Cloudflare gestisce il certificato automaticamente).

## Opzione B — GitHub Actions (Wrangler)

Nel repo c'è già `.github/workflows/deploy-website.yml`: deploya `website/` a ogni push che
tocca `website/**`. Richiede due **secret** nel repo GitHub
(*Settings → Secrets and variables → Actions*):

| Secret | Dove trovarlo |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare → My Profile → API Tokens → Create (template "Edit Cloudflare Pages") |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard → sidebar / URL dell'account |

Finché i secret non ci sono, il workflow **si salta da solo** (resta verde). Il progetto Pages
(`wp-aissistant-site`) viene creato al primo deploy.

## Note

- I link **Accedi/Registrati** del sito puntano al panel
  (`https://panel-production-ed34.up.railway.app`) — configurati in `LINKS` in fondo a
  `website/index.html`. Non esiste ancora una registrazione self-service, quindi "Registrati"
  porta al login del panel: cambialo se aggiungi un flusso di signup.
- I **prezzi** nel sito sono d'esempio: allineali all'offerta reale (e ai piani/Stripe).
- `website/_headers` imposta header di sicurezza di base; Cloudflare Pages lo applica in automatico.
