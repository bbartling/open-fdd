# Caddy LAN ingress

Caddy is the recommended LAN ingress for Open-FDD Rust edge deployments.

## Local dev — `openfdd_local_caddy_up.sh` (recommended on bench)

Uses `docker-compose.local.yml` + `docker-compose.local.caddy.yml` and the **local** image (`open-fdd-openfdd-bridge:local`).

**Prerequisite:** build the local image first:

```bash
./scripts/openfdd_local_up.sh --build
```

**Remote TLS dial-in** (production-like; self-signed cert):

```bash
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip <your-lan-ip>
```

Regenerate cert if the LAN IP changed:

```bash
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip <your-lan-ip> --regen-certs
```

| Flag | Purpose |
|------|---------|
| `--mode tls` | HTTPS on :443, redirect :80 → HTTPS (default) |
| `--mode http` | HTTP only on :80 |
| `--lan-ip ADDR` | Include IP in cert SANs (auto-detected if omitted) |
| `--regen-certs` | Force new `workspace/deploy/caddy/certs/cert.pem` |

Open from another machine: **https://\<LAN-IP\>/** — accept self-signed warning.

Login: use plaintext from `workspace/bootstrap_credentials.once.txt` (not bcrypt hashes in `auth.env.local`).

Full dev recipes: [local-dev.md](./local-dev.md).

## Compose profiles (GHCR / production compose)

From repo root:

```bash
export OPENFDD_COMPOSE_ROOT=$PWD

# Bridge + HTTP Caddy
docker compose -f docker/compose.edge.rust.yml \
  --profile desktop-json-csv --profile caddy-http up -d

# Bridge + TLS Caddy (generate certs first)
openfdd-edge tls generate --cn openfdd.local --out workspace/deploy/caddy/certs
docker compose -f docker/compose.edge.rust.yml \
  --profile desktop-json-csv --profile caddy-tls up -d
```

## Verify

HTTP:

```bash
curl -fsS http://localhost/api/health
```

TLS:

```bash
curl -kfsS https://localhost/api/health
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENFDD_CADDY_ENABLED` | `0` | Set `1` when Caddy is active |
| `OPENFDD_CADDY_MODE` | `off` | `off`, `http`, or `tls` |
| `OPENFDD_CADDY_HOSTNAME` | `openfdd.local` | TLS site name |
| `OPENFDD_CADDY_TLS_CN` | `openfdd.local` | Cert CN |
| `OPENFDD_CADDY_CERT_DIR` | `workspace/deploy/caddy/certs` | Host cert directory |

Caddyfiles live under `docker/caddy/Caddyfile.http` and `docker/caddy/Caddyfile.tls`.

## Direct dev mode

For local development without Caddy, run the bridge on `127.0.0.1:8080`:

```bash
./scripts/openfdd_local_up.sh
```

With Caddy for remote access:

```bash
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip <YOUR_LAN_IP>
```

Auth remains enabled by default. See [local-dev.md](./local-dev.md).
