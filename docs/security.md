# Security and Caddy Bootstrap

This document describes how to protect Open-FDD endpoints with **Caddy** (basic auth), which services are **unencrypted by default**, and **hardening** best practices. The project defaults to **non-TLS**; TLS (including self-signed certificates) is optional.

---

## Quick bootstrap with Caddy and basic auth

1. **Start the stack** (including optional Caddy):
   ```bash
   cd open-fdd
   docker compose -f platform/docker-compose.yml up -d
   ```
   This starts API (8000), Grafana (3000), TimescaleDB (5432), BACnet server (8080 on host), and **Caddy on port 8088**.

2. **Access through Caddy** (single entry point with basic auth):
   - **URL:** `http://localhost:8088`
   - **Default username:** `openfdd`
   - **Default password:** `xyz` (for local/testing only; change before any production or exposed use)

   The bundled Caddyfile routes API paths (e.g. `/docs`, `/api/*`, `/sites*`, `/analytics/*`, `/health`) to the Open-FDD API and all other paths to Grafana at `/`. All routes require this one basic-auth credential.

3. **Without Caddy:** You can still use the services directly (no auth):
   - API: http://localhost:8000/docs  
   - Grafana: http://localhost:3000  
   Do not expose these ports to untrusted networks without a reverse proxy and auth.

---

## Default password and how to change it

- The Caddyfile uses a **bcrypt hash** for the password. The default hash in the repo corresponds to password **`xyz`**.
- **Change the password** (recommended before production):
  1. Generate a new hash:
     ```bash
     docker run --rm caddy:2 caddy hash-password --plaintext 'your_secure_password'
     ```
  2. Open `platform/caddy/Caddyfile` and replace the hash on the `openfdd` line with the new output.
  3. Restart Caddy: `docker compose -f platform/docker-compose.yml restart caddy`.

- **Advanced / multiple users:** Edit the `basic_auth` block in the Caddyfile and add more lines (one per `username hash`). Use `caddy hash-password` for each password. For SSO or advanced auth, consider Caddy’s JWT or forward-auth and an IdP instead of basic auth.

---

## Services: encryption and exposure

| Service            | Port  | Encrypted by default? | Notes |
|--------------------|-------|------------------------|--------|
| **API**            | 8000  | No (HTTP)              | Put behind Caddy; do not expose directly. |
| **Grafana**        | 3000  | No (HTTP)              | Same; use Caddy (or Grafana’s own auth). |
| **TimescaleDB**   | 5432  | No (plain PostgreSQL)  | Not TLS by default. Keep on internal network only. |
| **BACnet server** | 8080  | No (HTTP API)          | Host network; protect with firewall or Caddy on host. |

- **Recommendation:** Expose only Caddy (e.g. 8088 or 443) to the building/remote network. Do not expose 5432, 8000, 3000, or 8080 to the internet. Use Caddy basic auth (and optionally TLS) for API and Grafana; keep the database and BACnet server behind the firewall.

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

## Summary

- **Bootstrap:** Start the stack; use `http://localhost:8088` with user `openfdd` and default password `xyz` (change before production).
- **Passwords:** Change default by running `caddy hash-password` and updating the Caddyfile; use strong passwords for Grafana and Postgres.
- **Unencrypted by default:** API, Grafana, TimescaleDB, and BACnet API are plain HTTP/TCP; protect them with network isolation and Caddy (and optional TLS).
- **Hardening:** Strong passwords, expose only Caddy, keep DB and internal services off the public internet, keep software updated.
- **TLS:** Optional; default is non-TLS. Add self-signed or Let’s Encrypt via Caddy when you need HTTPS.
