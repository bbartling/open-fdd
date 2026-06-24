# Caddy LAN ingress

Caddy is the recommended LAN ingress for Open-FDD Rust edge deployments.

## Compose profiles

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

For local development without Caddy, run the bridge on `127.0.0.1:8080` with `OPENFDD_CADDY_MODE=off`. Auth remains enabled by default.
