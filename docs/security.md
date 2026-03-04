# Security and Caddy Bootstrap

This document describes how to protect Open-FDD endpoints with **Caddy** (basic auth), which services are **unencrypted by default**, and **hardening** best practices. The project defaults to **non-TLS**; TLS (including self-signed certificates) is optional.

**What is Caddy?** A small web server in front of the API and the **React frontend**—one entry point (e.g. port 8088) with optional **basic auth** and **HTTPS**. Optional **Grafana** (when started with `--with-grafana`) is available at `/grafana`. By default Open-FDD does not run Caddy; this doc explains how to enable it for a protected entry point.

---

## Architecture: frontend, API, and Caddy

- **React frontend** runs in its own container (port 5173 in dev; built and served via Caddy in production-style setups). It uses **Bearer token** auth against the Open-FDD API when `OFDD_API_KEY` is set: all requests (and the WebSocket at `/ws/events`) send `Authorization: Bearer <key>`. See [Frontend API key (Bearer)](#frontend-api-key-bearer) below for where the key is sent.
- **API** (FastAPI) serves REST and WebSocket; when `OFDD_API_KEY` is set, it requires Bearer auth on all endpoints except `/health`, `/`, `/docs`, `/redoc`, `/openapi.json`, and `/app` (legacy static config UI).
- **Caddy** sits in front of both: it enforces **basic auth** (one login for the browser), then proxies to the API and frontend. When proxying to the API, Caddy adds the **X-Caddy-Auth** header (`header_up` in the Caddyfile) so the API accepts those requests without a Bearer token. So you sign in once with openfdd/xyz and the dashboard and API calls work without a second login. The web app can still send Bearer tokens when built with `VITE_OFDD_API_KEY`; when behind Caddy, the API trusts either Bearer or X-Caddy-Auth. **Best practice:** keep the frontend in its own container; do not serve the compiled React app from FastAPI as static files. Caddy (or another reverse proxy) serves the frontend and proxies API/WebSocket.

---

## Frontend API key (Bearer)

When `VITE_OFDD_API_KEY` is set (at frontend build time), the frontend sends it everywhere it talks to the backend: `apiFetch()` in `frontend/src/lib/api.ts` adds `Authorization: Bearer <key>` to all REST calls (sites, equipment, points, faults, config, FDD status, data model, etc.), `fetchCsv()` in `frontend/src/lib/csv.ts` adds the same header for CSV downloads, and the WebSocket in `frontend/src/hooks/use-websocket.ts` connects to `/ws/events?token=<key>`, which the backend accepts for WebSocket auth when an API key is configured.

---

## Quick bootstrap with Caddy and basic auth

1. **Start the stack** (from repo root):
   ```bash
   ./scripts/bootstrap.sh
   ```
   This starts DB, API (8000), frontend (5173), BACnet server (8080), scrapers, FDD loop, and **Caddy on port 8088**. **Grafana is not started by default**; use `./scripts/bootstrap.sh --with-grafana` to include it (then access at `http://localhost:8088/grafana` or http://localhost:3000).

2. **Access through Caddy** (single entry point with basic auth):
   - **URL:** `http://localhost:8088`
   - **Default username:** `openfdd`
   - **Default password:** `xyz` (for local/testing only; change before any production or exposed use)

   The bundled Caddyfile routes API paths to the Open-FDD API, **WebSocket** `/ws/*` to the API, and `/*` to the **React frontend**. If Grafana was started with `--with-grafana`, it is available at `http://localhost:8088/grafana`. All routes require this one basic-auth credential. The React app then uses the **API key** (from `VITE_OFDD_API_KEY` at build time) for Bearer auth to the API.

3. **Without Caddy:** You can still use the services directly (no auth if `OFDD_API_KEY` is unset):
   - Frontend: http://localhost:5173  
   - API: http://localhost:8000/docs  
   - Grafana (if started): http://localhost:3000  
   Do not expose these ports to untrusted networks without a reverse proxy and auth.

4. **Browser "Not secure" or "Your connection is not private":** Over plain HTTP (e.g. http://192.168.204.16:8088/), browsers show a "Not secure" or "connection not private" warning. That is expected without TLS. Use **http://** (not https://) so you are not blocked by a bad certificate. For production, add HTTPS (e.g. Caddy with TLS).

---

## Default password and how to change it

- The Caddyfile uses a **bcrypt hash** for the password. The default hash in the repo corresponds to password **`xyz`**.
- **Change the password** (recommended before production):
  1. Generate a new hash:
     ```bash
     docker run --rm caddy:2 caddy hash-password --plaintext 'your_secure_password'
     ```
  2. Open `stack/caddy/Caddyfile` and replace the hash on the `openfdd` line with the new output.
  3. Restart Caddy: `docker compose -f stack/docker-compose.yml restart caddy` (from repo root).

- **Advanced / multiple users:** Edit the `basic_auth` block in the Caddyfile and add more lines (one per `username hash`). Use `caddy hash-password` for each password. For SSO or advanced auth, consider Caddy’s JWT or forward-auth and an IdP instead of basic auth.

---

## Services: encryption and exposure

| Service            | Port  | Encrypted by default? | Notes |
|--------------------|-------|------------------------|--------|
| **API**            | 8000  | No (HTTP)              | Put behind Caddy; do not expose directly. Bearer auth when `OFDD_API_KEY` is set. |
| **Frontend**       | 5173  | No (HTTP)              | React app; use Caddy to serve and protect. Sends Bearer token to API. |
| **Grafana**        | 3000  | No (HTTP)              | Optional (--with-grafana); use Caddy at /grafana or Grafana's own auth. |
| **TimescaleDB**   | 5432  | No (plain PostgreSQL)  | Not TLS by default. Keep on internal network only. |
| **BACnet server** | 8080  | No (HTTP API)          | Host network; protect with firewall or Caddy on host. |

- **Recommendation:** Expose only Caddy (e.g. 8088 or 443) to the building/remote network. Do not expose 5432, 8000, 5173, 3000, or 8080 to the internet. Use Caddy basic auth (and optionally TLS) for the frontend and API; keep the database and BACnet server behind the firewall. The React frontend runs in its own container and is served by Caddy (or another reverse proxy), not as static files from the FastAPI process.

---

## Hardening best practices

1. **Passwords**
   - Do not use default `openfdd` / `xyz` in production. Change via `caddy hash-password` and update the Caddyfile.
   - Use strong, unique passwords (or a secrets manager) for Grafana (`GF_SECURITY_ADMIN_PASSWORD`), Postgres (`POSTGRES_PASSWORD`), and Caddy basic auth.

2. **Network**
   - Run TimescaleDB and internal services on a private Docker network; bind DB to localhost or internal IP only if needed.
   - Restrict firewall so only Caddy’s port (and optionally SSH) is reachable from outside.

3. **Reverse proxy**
   - Use Caddy in front of API and Grafana so one place enforces auth and (optionally) TLS.
   - Basic auth over plain HTTP is weak; prefer HTTPS when possible (see below).

4. **Principle of least privilege**
   - Run containers as non-root where possible; avoid sharing host network unless required (e.g. BACnet).
   - Limit Grafana sign-up and use strong admin credentials.

5. **Updates and hygiene**
   - Keep Caddy, Grafana, TimescaleDB, and the OS updated. Rotate credentials after compromise or periodically.

---

## Throttling and rate limiting

### 1. No API rate limiting by default

Open-FDD does **not** rate-limit incoming HTTP requests to the API. There is no built-in cap on how often clients can call the API. If you need to limit how often external clients (e.g. a busy integration or cloud poller) can call the API, add rate limiting at the reverse proxy (e.g. Caddy with a rate-limit module) or with rate-limit middleware in front of the app.

### 2. Outbound: OT/building network is paced

The application **does** throttle its own outbound traffic to the building and OT network. We do not continuously hammer BACnet or other building systems. Load is paced by configuration **and by which points you scrape**:

| Component | Config | Effect |
|-----------|--------|--------|
| **BACnet scraper** | `bacnet_scrape_interval_min` (e.g. 5) | Polls points on a fixed interval (e.g. every 5 minutes), not in a burst. |
| **BACnet scraper** | **Data model or CSV** | The scraper polls only the points it is configured with: **by default, points in the data model** that have `bacnet_device_id` and `object_identifier` (e.g. added via CRUD or after **POST /bacnet/point_discovery_to_graph** and data-model export/import). If none exist, it can fall back to a **curated CSV**. Throttling depends on **how many points** are defined (in the DB or in the CSV). Best practice: scrape only the points needed for FDD and HVAC health. See [BACnet overview](bacnet/overview#discovery-and-getting-points-into-the-data-model). |
| **FDD rule loop** | `rule_interval_hours` (e.g. 3) | Runs fault detection on a schedule (e.g. every 3 hours); each run pulls data from the DB, not from BACnet. |
| **Weather scraper** | `open_meteo_interval_hours` (e.g. 24) | Fetches weather once per interval (e.g. daily). |

So outbound load on the OT network is predictable and tunable. **Define only the points you need** (in the data model via CRUD or point_discovery_to_graph + export/import, or in a curated CSV), then adjust intervals via `OFDD_*` environment variables. See [Configuration](configuration) and [BACnet overview](bacnet/overview#discovery-and-getting-points-into-the-data-model).

### 3. Inbound: rate limiting at the reverse proxy (e.g. Caddy)

If you need to **throttle incoming traffic** to the API—for example to protect the API and OT network from aggressive polling, misconfigured integrators, or abuse—enforce rate limiting at the reverse proxy or with middleware. Open-FDD does not implement this itself; use Caddy (with a rate-limit module), nginx, or application middleware.

**Using Caddy for rate limiting**

Caddy can throttle requests per client (e.g. per IP or per authenticated user) when configured with a rate-limiting capability. The standard Caddy build does not include an HTTP rate-limit directive; you add it by building Caddy with a module (e.g. `xcaddy build --with github.com/mholt/caddy-ratelimit`) or by using a distribution that includes one. Once available, you configure a rate-limit zone in the Caddyfile (e.g. limit by `{remote_host}` or by a header), then apply it to the blocks that proxy to the API (and optionally Grafana). Typical choices are a cap per IP (e.g. 60 requests per minute) or per client identity when using auth. Exceeding the limit returns `429 Too Many Requests`; the client can retry after the window resets.

Example (conceptual; syntax depends on the module you use):

```caddyfile
:8088 {
  rate_limit {
    zone api { key {remote_host} events 60 duration 1m }
  }
  handle /api/* {
    rate_limit api
    reverse_proxy api:8000
  }
  # ... basic_auth and other handle blocks
}
```

Adjust the zone (events per duration) to match your OT network and integration requirements. For official options and current syntax, see [Caddy’s module documentation](https://caddyserver.com/docs/modules/) and the documentation for the rate-limit module you build or install.

---

## TLS (optional): self-signed certificates

The project **default is non-TLS**. If you want HTTPS in front of Caddy:

1. **Option A – Caddy automatic HTTPS (public hostname)**  
   If you have a public hostname and port 80/443, change the Caddyfile address to your domain; Caddy will obtain and renew Let’s Encrypt certs automatically.

2. **Option B – Self-signed certificate for Caddy**  
   For internal or lab use:
   - Generate a self-signed cert (e.g. with `openssl`).
   - In the Caddyfile, use `tls /path/to/cert.pem /path/to/key.pem` and listen on `:443` (or another port).
   - Mount the cert and key into the Caddy container and point Caddyfile to those paths.
   - Browsers will show a certificate warning; accept or install the CA for your environment.

Example Caddyfile snippet for self-signed (conceptual):

```caddyfile
https://0.0.0.0:8443 {
  tls /etc/caddy/cert.pem /etc/caddy/key.pem
  basic_auth /* { ... }
  # same handle/reverse_proxy blocks as :8088
}
```

Generate self-signed (host):

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=openfdd.local"
```

Mount `cert.pem` and `key.pem` into the Caddy container and reference them in `tls`.

---

## Troubleshooting

**API returns 401 (Unauthorized) after you pass Basic auth in the browser**

The API trusts requests that carry the internal header `X-Caddy-Auth` (set by Caddy after Basic auth). The API only checks this when the env var `OFDD_CADDY_INTERNAL_SECRET` is set in the API container and matches the value Caddy sends. If you added or changed this after the stack was already running, the API container may not have the variable. Recreate the API so it picks up the env:

```bash
cd stack && docker compose up -d --force-recreate api
```

Or from the repo root: `./scripts/bootstrap.sh --build api`. Then hard-refresh or use an incognito window and sign in again with Basic auth.

**WebSocket to `/ws/events` fails or closes immediately**

When access is through Caddy with Basic auth, the browser may not send credentials on the WebSocket upgrade. The API also accepts the same `X-Caddy-Auth` header on the WebSocket endpoint, so if Caddy is forwarding the request (after Basic auth), the WebSocket should work. Ensure the API has been recreated with `OFDD_CADDY_INTERNAL_SECRET` as above. If the WebSocket still fails (e.g. due to browser or proxy behavior), the UI will keep working; live updates will resume when the connection succeeds.

---

## Summary

- **Bootstrap:** Start the stack; use `http://localhost:8088` (or your Caddy port, e.g. 80) with user `openfdd` and default password `xyz` (change before production).
- **Passwords:** Change default by running `caddy hash-password` and updating the Caddyfile; use strong passwords for Grafana and Postgres.
- **Unencrypted by default:** API, Grafana, TimescaleDB, and BACnet API are plain HTTP/TCP; protect them with network isolation and Caddy (and optional TLS).
- **Hardening:** Strong passwords, expose only Caddy, keep DB and internal services off the public internet, keep software updated.
- **Throttling:** (1) No API rate limiting by default. (2) Outbound traffic to the OT/building network is paced (BACnet scrape, FDD loop, weather intervals). (3) To throttle incoming API traffic, use the reverse proxy (e.g. Caddy with a rate-limiting module) or middleware.
- **TLS:** Optional; default is non-TLS. Add self-signed or Let’s Encrypt via Caddy when you need HTTPS.
