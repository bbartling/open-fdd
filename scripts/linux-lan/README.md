# Linux LAN Option A (Caddy + systemd)

This folder provides ready private-LAN baselines:

- Single ingress via **Caddy** with Basic Auth.
- Backend services bound to localhost/private ports.
- systemd units for:
  - Open-FDD gateway (`8765`)
  - Open-FDD MCP RAG (`8090`)
  - Open-FDD UI (Vite on `5173`)
  - DIY BACnet server (`8080`)
  - easy-aso supervisor (`18090`)

Caddy variants:

- `Caddyfile` — simple HTTP + Basic Auth ingress.
- `Caddyfile.cidr` — same, plus CIDR source-IP gate (defaults to `10.0.0.0/8`).
- `Caddyfile.tls-internal` — HTTPS (`tls internal`) + CIDR gate + Basic Auth (defaults to `10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`).

## 1) Install apps/venvs (example paths)

- `/opt/open-fdd` (repo clone + `.venv` with `open-fdd[desktop,optimization]`)
- `/opt/easy-aso` (repo clone + `.venv` with `easy-aso[platform]`)
- `/opt/diy-bacnet-server` (repo clone + `.venv`)

## 2) Env file

```bash
sudo mkdir -p /etc/openfdd
sudo cp scripts/linux-lan/bench.env.example /etc/openfdd/bench.env
sudo chmod 600 /etc/openfdd/bench.env
sudo nano /etc/openfdd/bench.env
```

Set real random tokens for keys in that file.

## 3) Caddy

```bash
# pick one:
sudo cp scripts/linux-lan/Caddyfile /etc/caddy/Caddyfile
# sudo cp scripts/linux-lan/Caddyfile.cidr /etc/caddy/Caddyfile
# sudo cp scripts/linux-lan/Caddyfile.tls-internal /etc/caddy/Caddyfile
sudo caddy hash-password --plaintext 'change-me-now'
```

Create a caddy systemd override with auth env:

```bash
sudo systemctl edit caddy
```

Add:

```ini
[Service]
Environment="OPENFDD_BASIC_AUTH_USER=operator"
Environment="OPENFDD_BASIC_AUTH_HASH=$2a$14$replace-with-caddy-hash"
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart caddy
sudo systemctl enable caddy
```

For CIDR-gated variants, make sure `@lan remote_ip` includes the private CIDRs your bench actually uses (for example 10/8, 192.168/16, 172.16/12), then tighten further to specific subnets when ready.

## 4) systemd units

```bash
sudo cp scripts/linux-lan/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now diy-bacnet-server openfdd-gateway openfdd-mcp-rag openfdd-ui-vite easyaso-supervisor
```

## 5) Health checks

From the Linux host:

```bash
curl -sf http://127.0.0.1:8765/health
curl -sf http://127.0.0.1:8090/health
curl -sf http://127.0.0.1:18090/health
curl -sf http://127.0.0.1:8080/server_hello -H "Authorization: Bearer $BACNET_RPC_API_KEY"
```

From a LAN client/browser:

- Open `http://<bench-lan-ip>/`
- Login via Basic Auth (Caddy)
- UI uses `/api/openfdd` proxy path by default (`VITE_DESKTOP_BRIDGE_BASE=/api/openfdd`)

If using `Caddyfile.tls-internal`, use `https://<bench-lan-ip>/` and trust Caddy internal CA on clients.

## Notes

- Keep app ports firewalled from non-localhost; expose Caddy only.
- Use different keys for DIY BACnet, easy-aso supervisor, and MCP action tools.
- Option A is intentionally simple; upgrade to forward-auth/OIDC later if needed.
