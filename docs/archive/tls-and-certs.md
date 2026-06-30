# TLS and self-signed certificates

For LAN deployments without a public CA, generate self-signed certificates with Rust:

```bash
openfdd-edge tls generate --cn openfdd.local --out workspace/deploy/caddy/certs
```

This writes:

- `cert.pem`
- `key.pem` (mode `600` on Unix)

SANs include the CN, `localhost`, `127.0.0.1`, and an optional LAN IP:

```bash
openfdd-edge tls generate --cn openfdd.local --out workspace/deploy/caddy/certs --lan-ip 192.168.1.50
```

## Caddy TLS mode

Use compose profile `caddy-tls` (see [deployment/caddy.md](../deployment/caddy.md)). Browsers will warn on self-signed certs — expected for lab/edge use.

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENFDD_CADDY_CERT_DIR` | Host path to cert directory (default `workspace/deploy/caddy/certs`) |
| `OPENFDD_CADDY_TLS_CN` | Certificate common name |

No Python or OpenSSL scripts are required for cert generation.
