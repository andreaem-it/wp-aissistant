# Deploy: reverse proxy & TLS

In produzione **non** esporre il backend direttamente: mettici davanti un reverse proxy che
termina il TLS (HTTPS) e inoltra al backend sulla rete privata. Questa cartella contiene due
esempi equivalenti — scegline uno:

- **[`Caddyfile`](./Caddyfile)** — Caddy, con **HTTPS automatico** (Let's Encrypt). Il più semplice.
- **[`nginx.conf`](./nginx.conf)** — Nginx, con TLS via certificati (es. certbot).

## Principi

1. **Il backend non è pubblico.** Solo il proxy è esposto (porte 80/443). Nel `docker-compose`
   di produzione **non** pubblicare la porta `8000` del servizio `backend` sull'host: lasciala
   raggiungibile solo dalla rete interna (dal proxy e da Prometheus).

2. **TLS al proxy.** Caddy ottiene e rinnova il certificato da solo; con Nginx usa certbot e
   punta `ssl_certificate` / `ssl_certificate_key` ai file emessi.

3. **Real client IP.** Il backend usa l'IP del client per il rate limiting di `/chat`. Dietro
   proxy, l'IP diretto è quello del proxy: l'immagine avvia `uvicorn --proxy-headers`, che legge
   `X-Forwarded-For`. **Importante:** imposta la env `FORWARDED_ALLOW_IPS` con l'indirizzo/rete
   del proxy (es. `FORWARDED_ALLOW_IPS=proxy` o l'IP della rete Docker), altrimenti uvicorn si
   fida solo di `127.0.0.1` e l'IP inoltrato viene ignorato. Sia Caddy che l'esempio Nginx
   inviano già `X-Forwarded-For` e `X-Forwarded-Proto`.

4. **`/metrics` non pubblico.** Entrambi gli esempi rispondono `404` su `/metrics` verso
   l'esterno. Prometheus deve scrapare il backend **internamente** (`backend:8000/metrics`).

5. **CORS in produzione.** Metti `CORS_ALLOW_ALL=false` e configura gli origin per-client via
   `POST /admin/clients/{id}/origins` (vedi README principale). Aggiungi l'origin del panel a
   `PANEL_ORIGINS`.

## Stack di produzione pronto

Alla root del repo c'è **[`docker-compose.prod.yml`](../docker-compose.prod.yml)**: backend
dall'immagine GHCR, Caddy davanti (questo `Caddyfile`), porta 8000 **non** esposta, CORS
ristretto e `FORWARDED_ALLOW_IPS` già impostato.

```bash
export ADMIN_API_KEY=<token-robusto>
export POSTGRES_PASSWORD=<password-robusta>
# edita deploy/Caddyfile con il tuo dominio, poi:
docker compose -f docker-compose.prod.yml up -d
```

Con **Nginx** invece di Caddy: sostituisci il servizio `caddy` con un `nginx:alpine`, monta
`nginx.conf` in `/etc/nginx/conf.d/default.conf` e i certificati in `/etc/letsencrypt`.
