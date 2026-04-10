# Security and Caddy Bootstrap

This document describes how to protect Open-FDD endpoints with **Caddy** (reverse proxy) when you use it, which services are **unencrypted by default** in a typical dev layout, and **hardening** best practices. The project defaults to **non-TLS** for lab stacks; TLS (including self-signed certificates) is optional.

## Current default (VOLTTRON-first)

The **default** path in this monorepo is **`./afdd_stack/scripts/bootstrap.sh`**: **VOLTTRON 9** clone/venv and optional **`--compose-db`** (Postgres/Timescale + Open-FDD init SQL). **Docker Compose** in this repo does **not** start Caddy, the FastAPI container, the React container, BACnet gateway, or scrapers — see **`afdd_stack/legacy/README.md`** and **[Getting started](getting_started.md)**.

The sections below apply when you run **FastAPI + React + Caddy yourself** (local development or a custom deployment). For **VOLTTRON Central** perimeter security, use **upstream VOLTTRON** documentation.

---

## Reverse proxy: current file vs future hardening

- **Canonical config in the repo:** [`stack/caddy/Caddyfile`](../stack/caddy/Caddyfile) — checked-in Caddy config for a **single HTTP entry point** on port **80**: `handle /api*` (with `uri strip_prefix /api`), `/auth*`, `/ws*`, and `/ai*` are proxied to the API; `handle /*` serves the React frontend. This matches the frontend’s default **`VITE_API_BASE=/api`** in Docker Compose: browser calls go to same-origin paths under `/api`, `/auth`, and `/ws`.
- **Status:** When Caddy is running in **your** deployment, use **`http://localhost`** (or `http://<lan-host>`) as the main URL; use **http://localhost:8000** (API) and **http://localhost:5173** (frontend direct) when debugging without the proxy. The **default repo compose file** does not start Caddy.
- **Future hardening:** Optional Caddy **basic auth**, **TLS**, rate limiting, and stricter perimeter defaults are documented below as **targets**; they are not all enabled in the committed file.

**What is Caddy?** A small web server in front of the API and the **React frontend**. The **committed** `stack/caddy/Caddyfile` is a lightweight starting point; this page also documents **target** patterns (basic auth, `X-Caddy-Auth`, full API routes) for when you extend or harden the proxy. Optional **Grafana** (compose **`grafana`** profile) can be exposed via Caddy (e.g. `/grafana`) once you add a reverse proxy. The **default** bootstrap does not start Caddy; see [Quick bootstrap with Caddy (custom deployments)](#quick-bootstrap-with-caddy-custom-deployments).

---

## Architecture: frontend, API, and Caddy

- **React frontend** (when you run it, e.g. dev server or container on **5173**; Caddy’s **`/*`** can route there). **App login:** users sign in at **`/login`**; the API returns a short-lived **JWT access token** (browser **sessionStorage**) and an **HttpOnly** refresh cookie (`/auth/*`). REST uses **`Authorization: Bearer <access_token>`**; the WebSocket uses **`/ws/events?token=<access_token>`** (or the API-key token path in [Frontend and API authentication](#frontend-and-api-authentication)).
- **API** (FastAPI) requires auth when **`OFDD_API_KEY`** and/or **app-user** config is set (`OFDD_APP_USER`, `OFDD_APP_USER_HASH`, **`OFDD_JWT_SECRET`** — all three together). Valid credentials are **`Bearer`** matching **`OFDD_API_KEY`** or a valid **access JWT**. Exempt paths include `/`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/app` (and `/app/*`), and **`/auth/*`**. Partial app-user configuration is rejected explicitly: **`/auth/login`** and related routes return **503** (`AUTH_CONFIG_ERROR` / `AUTH_NOT_CONFIGURED`), while the global API middleware returns **500** with `AUTH_CONFIG_ERROR` for other protected paths—never a silent fallback.
- **Machine clients** (VOLTTRON agents, curl, **Open Claw** on a Windows bench) should rely on **`OFDD_API_KEY`** and **`Authorization: Bearer`**, not the browser cookie flow — see [Open‑Claw integration](openclaw_integration#1e-openclaw-on-a-different-machine-than-open-fdd-split-setup).
- **Caddy** can be extended with **basic auth** + **`X-Caddy-Auth`** / **`OFDD_CADDY_INTERNAL_SECRET`** (optional); see [Caddyfile for protecting the entire API](#caddyfile-for-protecting-the-entire-api). **Best practice:** use a reverse proxy as the operator entry point when exposing API + UI to a network.

---

## Frontend and API authentication
{: #frontend-and-api-authentication }

| Mode | Typical use | How it works |
|------|-------------|--------------|
| **Dashboard login** | Human operators via browser | `POST /auth/login` → access JWT in session + HttpOnly refresh cookie; `apiFetch` attaches `Bearer` access token; WebSocket uses access token in query string. |
| **`OFDD_API_KEY`** | Scrapers, scripts, agents, LAN test bench | `Authorization: Bearer <OFDD_API_KEY>` on REST; WebSocket may use `?token=<key>` when no JWT is in use. |

Configure dashboard login by setting **`OFDD_APP_USER`**, **`OFDD_APP_USER_HASH`**, and **`OFDD_JWT_SECRET`** in **`afdd_stack/stack/.env`** (see script comments in a legacy fork or generate hashes per FastAPI auth docs). Remove or empty **`OFDD_API_KEY`** / app-user keys for an open local dev API only if you accept the risk.

**Legacy note:** Older **`./scripts/bootstrap.sh --user`** / **`--mode model`** guardrails applied when Compose started the **model** stack automatically; the **current** `afdd_stack/scripts/bootstrap.sh` does not manage those flags.

**Examples (password not on the argv):**

```bash
# Example: set secrets in afdd_stack/stack/.env (use your org’s password hashing for the app user), then start FastAPI/uvicorn and React yourself.
# Legacy one-liners that combined bootstrap + --user + full Docker rebuild are removed from the default bootstrap script.
```

After **`OFDD_JWT_SECRET`** or the app user changes, sign in again in the browser so tokens match the new secret; use **Sign out** (or `/logout`) if the UI still holds an old session.

**`VITE_API_BASE`:** When the frontend is built to sit behind a path-based proxy, **`/api`** keeps same-origin requests aligned with a Caddy strip-prefix pattern. Override with a full URL (e.g. `http://api-host:8000`) if the API is on another origin.

Older docs referred to baking **`VITE_OFDD_API_KEY`** into the frontend at build time; the supported operator path is now **login + JWT** (or unauthenticated local dev with auth disabled). A static API key in the bundle is discouraged for production.

**HTTPS behind a reverse proxy:** The API sees plain HTTP from the proxy. Set **`OFDD_TRUST_FORWARDED_PROTO=true`** on the API container when the edge proxy terminates TLS and sends **`X-Forwarded-Proto: https`**, so refresh cookies get the **`Secure`** flag. Leave **`false`** (default) for HTTP-only lab stacks so cookies stay usable over HTTP.

---

## Stack hardening (database, Caddy, secrets)
{: #stack-hardening-db-caddy-secrets }

Related tracking: **[Stack security hardening](https://github.com/bbartling/open-fdd/issues/73)** and **[dashboard / API authentication](https://github.com/bbartling/open-fdd/issues/72)**.

**Architecture rule:** **Frontend → API → database.** The React app must not talk to Postgres; only the API uses `OFDD_DB_DSN` on the Docker network (`db:5432`).

| Area | Repo default / guidance |
|------|-------------------------|
| **Postgres publish** | `docker-compose.yml` binds the DB port to **`127.0.0.1:5432`** only — tools on the **host** can use `psql` locally; **remote machines cannot** reach the DB via that mapping. For stricter production, **remove** the `ports:` block under `db` so only containers on the compose network can connect (admin via `docker exec` or a throwaway `psql` container). |
| **API / frontend host bind** | When using **compose** or **docker run** for API/frontend, **`OFDD_API_HOST_BIND`** and **`OFDD_FRONTEND_HOST_BIND`** control published ports **8000** and **5173**. The **default slim compose** in this repo does not publish those services; bind addresses matter when you add your own compose override or run **`uvicorn`/`npm run dev`** on the host. |
| **Edge TLS** | The committed Caddyfile serves **HTTP on :80** with security headers. For **HTTPS**, use a public DNS name and either Caddy automatic TLS or mounted certs; start with [`stack/caddy/Caddyfile.https.example`](../stack/caddy/Caddyfile.https.example) and set **`OFDD_TRUST_FORWARDED_PROTO=true`** on the API. **Do not** send `Strict-Transport-Security` on plain HTTP; the example adds HSTS only on the HTTPS site block. |
| **Caddy headers** | The bundled **`stack/caddy/Caddyfile`** sets `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy`. Optional: **CSP**, **rate limiting**, Caddy **basic auth** as a second layer — see [Caddyfile for protecting the entire API](#caddyfile-for-protecting-the-entire-api). |
| **Secrets** | **`afdd_stack/stack/.env`** is **gitignored**. Store **Argon2 hash**, **JWT secret**, and optional **`OFDD_API_KEY`** (machine-only — not for the browser UI) there. Never commit secrets. For Caddy **`X-Caddy-Auth`** flows, set **`OFDD_CADDY_INTERNAL_SECRET`**. Optional Grafana: **`GF_SECURITY_ADMIN_USER`** / **`GF_SECURITY_ADMIN_PASSWORD`** in `.env` instead of compose defaults. |

**WebSocket:** Same auth model as HTTP (access JWT or API key); no DB access from browser WebSocket code.

---

## Quick bootstrap with Caddy (custom deployments)

The **default** `afdd_stack/scripts/bootstrap.sh` does **not** start Caddy or the full Docker stack. Use **[Getting started](getting_started.md)** first.

If you run **FastAPI + React + Caddy** yourself (custom compose or manual processes):

1. **Start your stack** so the API listens on **8000**, the frontend on **5173**, and optionally Caddy on **80** using [`stack/caddy/Caddyfile`](../stack/caddy/Caddyfile) as a template. **Grafana** is optional via the compose **`grafana`** profile from `afdd_stack/stack/`.

2. **Access through Caddy** (**no basic auth** in the committed repo file today):
   - **URL:** `http://localhost` (port **80**)
   - **`/api*`** → API (prefix stripped), **`/auth*`** → API, **`/ws*`** → API, **`/ai*`** → API, **`/*`** → frontend (static build). From another machine on the LAN, use **`http://<server-ip>/`** the same way.

3. **Hardened entry point (future / manual):** To put the **entire** UI and API behind one login and optional TLS, follow [Caddyfile for protecting the entire API](#caddyfile-for-protecting-the-entire-api) below and test thoroughly. Example credentials like `openfdd` / `xyz` apply only after you add **basic_auth** to your Caddyfile—not in the default committed file.

4. **Without Caddy:** You can still use the services directly (no auth if `OFDD_API_KEY` is unset):
   - Frontend: http://localhost:5173  
   - API: http://localhost:8000/docs  
   - Grafana (if started): http://localhost:3000  
   Do not expose these ports to untrusted networks without a reverse proxy and auth.

5. **Browser "Not secure" or "Your connection is not private":** Over plain HTTP (e.g. `http://localhost/` or `http://192.168.x.x/`), browsers show a warning. That is expected without TLS. Use **http://** (not https://) unless you have configured HTTPS in Caddy. Production should use TLS when you deploy with HTTPS.

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
| **TimescaleDB**   | 5432  | No (plain PostgreSQL)  | Compose maps **`127.0.0.1:5432`** to the container so the host can use `psql` locally; remote clients do not get a LAN-wide DB port. Remove `ports` under `db` for internal-only DB. |
| **BACnet server** | 8080  | No (HTTP API)          | Host network; protect with firewall or Caddy on host. |

- **Recommendation:** When hardened, expose only Caddy (compose defaults to **port 80**; use **443** or another port with TLS when ready) to the building/remote network. Do not expose 5432, 8000, 5173, 3000, or 8080 to the internet. Plan for Caddy **basic auth** and **TLS** as security hardening matures; keep the database and BACnet server behind the firewall. The React frontend runs in its own container and is served by Caddy (or another reverse proxy), not as static files from the FastAPI process.

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

## Security scanning (Trivy)
{: #security-scanning-trivy }

During development, use **Trivy** to scan container images and the repo for vulnerabilities and misconfigurations. Run it after building images, when changing Dockerfiles or dependencies, and optionally in CI. See **[How-to: Trivy security scanning](howto/trivy)** for install, when to run, image and filesystem scan commands, and keeping docs up to date.

---

## Summary

- **Bootstrap:** Start the stack; the committed Caddyfile listens on **`http://localhost`** (port **80**) with **no** basic auth, and routes **`/api`**, **`/auth`**, **`/ws`**, and **`/ai`** to the API. Use **8000** / **5173** for direct debugging.
- **Auth:** Optional dashboard login (JWT + HttpOnly refresh cookie) and/or **`OFDD_API_KEY`** for machine clients; both can be configured together.
- **Passwords:** Change default by running `caddy hash-password` and updating the Caddyfile; use strong passwords for Grafana and Postgres.
- **Unencrypted by default:** API, Grafana, TimescaleDB, and BACnet API are plain HTTP/TCP; protect them with network isolation and Caddy (and optional TLS).
- **Hardening:** Strong passwords, expose only Caddy, keep DB and internal services off the public internet, keep software updated.
- **Throttling:** (1) No API rate limiting by default. (2) Outbound traffic to the OT/building network is paced (BACnet scrape, FDD loop, weather intervals). (3) To throttle incoming API traffic, use the reverse proxy (e.g. Caddy with a rate-limiting module) or middleware.
- **TLS:** Optional; default is non-TLS. Add self-signed or Let’s Encrypt via Caddy when you need HTTPS.
