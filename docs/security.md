# Security and Caddy Bootstrap

This document describes how to protect Open-FDD endpoints with **Caddy** (reverse proxy), which services are **unencrypted by default**, and **hardening** best practices. The project defaults to **non-TLS**; TLS (including self-signed certificates) is optional.

## Reverse proxy: current file vs future hardening

- **Canonical config in the repo:** [`stack/caddy/Caddyfile`](../stack/caddy/Caddyfile) — this is the **only** checked-in Caddy config today. It provides a **minimal** reverse proxy (e.g. port **80** → frontend, with `/ai*` routed to the API so Overview AI works through one entry point). It does **not** yet implement full API coverage, basic auth, or TLS.
- **Status:** Treat the bundled reverse-proxy path as **still needing test coverage and operational validation**. Prefer direct service ports (frontend, API) when debugging until you have confirmed Caddy behavior in your environment.
- **Later phases:** Stronger Open-FDD perimeter security—**basic auth**, routing the **full** API and WebSocket through Caddy, **TLS**, rate limiting, and tighter defaults—will be rolled out as part of **future security-hardening work**, not all of which is reflected in the committed `Caddyfile` yet.

**What is Caddy?** A small web server in front of the API and the **React frontend**. The **committed** `stack/caddy/Caddyfile` is a lightweight starting point; this page also documents **target** patterns (basic auth, `X-Caddy-Auth`, full API routes) for when those hardening phases land. Optional **Grafana** (when started with `--with-grafana`) can be exposed via Caddy (e.g. `/grafana`) once the proxy config is extended. Bootstrap starts the Caddy service with the compose file under `stack/`; see [Quick bootstrap with Caddy](#quick-bootstrap-with-caddy).

---

## Architecture: frontend, API, and Caddy

- **React frontend** runs in its own container (port 5173 in dev; built and served via Caddy in production-style setups). It uses **Bearer token** auth against the Open-FDD API when `OFDD_API_KEY` is set: all requests (and the WebSocket at `/ws/events`) send `Authorization: Bearer <key>`. See [Frontend API key (Bearer)](#frontend-api-key-bearer) below for where the key is sent.
- **API** (FastAPI) serves REST and WebSocket; when `OFDD_API_KEY` is set, it requires Bearer auth on all endpoints except `/health`, `/`, `/docs`, `/redoc`, `/openapi.json`, and `/app` (legacy static config UI).
- **Caddy** (when configured for hardening) can sit in front of both: **basic auth** (one browser login), then proxy to the API and frontend. With **`header_up X-Caddy-Auth`** in the Caddyfile and **`OFDD_CADDY_INTERNAL_SECRET`** on the API, the backend can trust requests that passed Caddy without requiring a Bearer token on every call. Until that layout is validated end-to-end, the **checked-in** `stack/caddy/Caddyfile` is simpler; the API may still be reached directly on port 8000. **Best practice:** keep the frontend in its own container; do not serve the compiled React app from FastAPI as static files. Use Caddy (or another reverse proxy) as the single entry point once your hardened config is tested.

---

## Frontend API key (Bearer)

When `VITE_OFDD_API_KEY` is set (at frontend build time), the frontend sends it everywhere it talks to the backend: `apiFetch()` in `frontend/src/lib/api.ts` adds `Authorization: Bearer <key>` to all REST calls (sites, equipment, points, faults, config, FDD status, data model, etc.), `fetchCsv()` in `frontend/src/lib/csv.ts` adds the same header for CSV downloads, and the WebSocket in `frontend/src/hooks/use-websocket.ts` connects to `/ws/events?token=<key>`, which the backend accepts for WebSocket auth when an API key is configured.

---

## Quick bootstrap with Caddy

1. **Start the stack** (from repo root):
   ```bash
   ./scripts/bootstrap.sh
   ```
   This starts DB, API (8000), frontend (5173), BACnet server (8080), scrapers, FDD loop, and **Caddy** (see `stack/docker-compose.yml`). Caddy publishes **host port 80** → container port 80 using **`stack/caddy/Caddyfile`**. **Grafana is not started by default**; use `./scripts/bootstrap.sh --with-grafana` to include it (then use http://localhost:3000, or add a `/grafana` route when you extend the Caddyfile).

2. **Access through the committed Caddyfile** (minimal reverse proxy — **no basic auth** in the repo file today):
   - **URL:** `http://localhost` (port **80**)
   - The checked-in config proxies **`/ai*`** to the API and **`/*`** to the **React dev server** (frontend container). Other API paths and `/ws/*` are **not** defined in that file; use **http://localhost:5173** (frontend) and **http://localhost:8000** (API) for full access while the single-entry-point layout is still being validated.

3. **Hardened entry point (future / manual):** To put the **entire** UI and API behind one login and optional TLS, follow [Caddyfile for protecting the entire API](#caddyfile-for-protecting-the-entire-api) below and test thoroughly. Example credentials like `openfdd` / `xyz` apply only after you add **basic_auth** to your Caddyfile—not in the default committed file.

4. **Without Caddy:** You can still use the services directly (no auth if `OFDD_API_KEY` is unset):
   - Frontend: http://localhost:5173  
   - API: http://localhost:8000/docs  
   - Grafana (if started): http://localhost:3000  
   Do not expose these ports to untrusted networks without a reverse proxy and auth.

5. **Browser "Not secure" or "Your connection is not private":** Over plain HTTP (e.g. `http://localhost/` or `http://192.168.x.x/`), browsers show a warning. That is expected without TLS. Use **http://** (not https://) unless you have configured HTTPS in Caddy. Production should use TLS in a later hardening phase.

---

## Caddyfile for protecting the entire API

The **committed** [`stack/caddy/Caddyfile`](../stack/caddy/Caddyfile) is intentionally **small** (see [Reverse proxy: current file vs future hardening](#reverse-proxy-current-file-vs-future-hardening)). The block below is an **example / target** for a **future hardened** setup: one entry point, optional **basic auth**, and most API routes (plus WebSocket) proxied with **`X-Caddy-Auth`**. It is **not** drop-in verified for every workflow yet—validate in your environment before relying on it for production. Use the same **secret** in `header_up X-Caddy-Auth` and in the API container env **`OFDD_CADDY_INTERNAL_SECRET`** so the API trusts requests that passed Caddy’s basic auth.

```caddyfile
# Listen on port 80 (or use :8088 and map 8088:8088 in docker-compose).
:80 {
	# Optional: basic auth (generate hash: docker run --rm caddy:2 caddy hash-password --plaintext 'your_password')
	# basic_auth /* {
	#   openfdd <bcrypt_hash>
	# }

	# API: REST, Swagger, WebSocket. Set OFDD_CADDY_INTERNAL_SECRET in the API container to match the value below.
	handle /ws/* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /docs {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /redoc {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /openapi.json {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /health {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /config* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /sites* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /equipment* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /points* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /faults* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /data-model* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /download* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /analytics* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /bacnet* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /jobs* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /capabilities* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}
	handle /ai* {
		header_up X-Caddy-Auth "your_internal_secret"
		reverse_proxy api:8000
	}

	# Optional: Grafana when started with --with-grafana
	# handle /grafana/* {
	#   reverse_proxy grafana:3000
	# }

	# Frontend (React)
	handle /* {
		reverse_proxy frontend:5173
	}
}
```

Then restart Caddy and recreate the API so it has `OFDD_CADDY_INTERNAL_SECRET` set: `./scripts/bootstrap.sh --build caddy api` (from repo root). See [Troubleshooting](#troubleshooting) if the API returns 401 or the WebSocket fails.

---

## Default password and how to change it

The **default committed** `stack/caddy/Caddyfile` does **not** include **basic auth** today. The following applies **after** you add a `basic_auth` block (e.g. using the [example Caddyfile](#caddyfile-for-protecting-the-entire-api) above):

- Use a **bcrypt hash** for each password (e.g. default example password **`xyz`** only if you paste the matching hash from docs/examples—do not use defaults in production).
- **Change the password** (required before production):
  1. Generate a new hash:
     ```bash
     docker run --rm caddy:2 caddy hash-password --plaintext 'your_secure_password'
     ```
  2. Open **`stack/caddy/Caddyfile`** and update the `basic_auth` user line(s) with the new hash(es).
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

- **Recommendation:** When hardened, expose only Caddy (compose defaults to **port 80**; use **443** or another port with TLS in later phases) to the building/remote network. Do not expose 5432, 8000, 5173, 3000, or 8080 to the internet. Plan for Caddy **basic auth** and **TLS** as security hardening matures; keep the database and BACnet server behind the firewall. The React frontend runs in its own container and is served by Caddy (or another reverse proxy), not as static files from the FastAPI process.

---

## Hardening best practices

1. **Passwords**
   - When you enable Caddy **basic auth**, do not use example defaults like `openfdd` / `xyz` in production. Change via `caddy hash-password` and update `stack/caddy/Caddyfile`.
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
| **BACnet scraper** | **Data model (DB)** | The scraper polls only points that have `bacnet_device_id` and `object_identifier` in the **data model** (CRUD, import, or after **POST /bacnet/point_discovery_to_graph**). The default Docker stack does **not** use a BACnet CSV for scrape config. Throttling depends on **how many points** are defined and the poll interval. Best practice: scrape only the points needed for FDD and HVAC health. See [BACnet overview](bacnet/overview#discovery-and-getting-points-into-the-data-model). |
| **FDD rule loop** | `rule_interval_hours` (e.g. 3) | Runs fault detection on a schedule (e.g. every 3 hours); each run pulls data from the DB, not from BACnet. |
| **Weather scraper** | `open_meteo_interval_hours` (e.g. 24) | Fetches weather once per interval (e.g. daily). |

So outbound load on the OT network is predictable and tunable. **Define only the points you need** in the data model (CRUD, import, or discovery → graph), then adjust intervals via the Config UI / data model or `OFDD_*` environment variables. See [Configuration](configuration) and [BACnet overview](bacnet/overview#discovery-and-getting-points-into-the-data-model).

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

## Security scanning (Trivy) — Phase 3

During development, use **Trivy** to scan container images and the repo for vulnerabilities and misconfigurations. Run it after building images, when changing Dockerfiles or dependencies, and optionally in CI. See **[How-to: Trivy security scanning](howto/trivy)** for install, when to run, image and filesystem scan commands, and keeping docs up to date.

---

## Summary

- **Bootstrap:** Start the stack; the committed Caddyfile listens on **`http://localhost`** (port **80**) with **no** basic auth. Use **5173** / **8000** for full app access until a hardened Caddyfile is tested. After adding basic auth, use the credentials you configured (not any example defaults in production).
- **Passwords:** Change default by running `caddy hash-password` and updating the Caddyfile; use strong passwords for Grafana and Postgres.
- **Unencrypted by default:** API, Grafana, TimescaleDB, and BACnet API are plain HTTP/TCP; protect them with network isolation and Caddy (and optional TLS).
- **Hardening:** Strong passwords, expose only Caddy, keep DB and internal services off the public internet, keep software updated.
- **Throttling:** (1) No API rate limiting by default. (2) Outbound traffic to the OT/building network is paced (BACnet scrape, FDD loop, weather intervals). (3) To throttle incoming API traffic, use the reverse proxy (e.g. Caddy with a rate-limiting module) or middleware.
- **TLS:** Optional; default is non-TLS. Add self-signed or Let’s Encrypt via Caddy when you need HTTPS.
