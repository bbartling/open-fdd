---
title: TLS and certificates
parent: Security
nav_order: 3
---

# TLS and certificates

Who generates, stores, and renews TLS material for Open-FDD on OT LANs — and how that ties into ZAP/Nmap bench testing.

Developer release cycle: [Security testing cycle](../developer/security-testing).

## Ownership

| Environment | Who owns certs | Storage |
|-------------|----------------|---------|
| Local / benserver bench | Developer / maintainer | `workspace/deploy/caddy/certs/` (`cert.pem`, `key.pem`) |
| Ansible edge (Acme, customer sites) | Site integrator | `/etc/openfdd/caddy/` on the VM (playbook-managed or manual) |
| Public internet | **Not in scope** | Open-FDD targets OT LAN; use site PKI or self-signed |

Open-FDD does **not** ship Let's Encrypt or public CA automation. OT benches use **self-signed** or customer-provided certs.

## Generate bench certs (local)

```bash
./scripts/setup_caddy_certs.sh
# or: ./scripts/setup_caddy_certs.sh --cn openfdd.local --out workspace/deploy/caddy/certs
```

Then start with TLS mode:

```bash
OFDD_CADDY_MODE=tls ./scripts/run_local.sh
# or pentest stack with OFDD_CADDY_MODE=tls
```

Caddy serves `:443` and redirects `:80` → HTTPS. Caddy adds **`Strict-Transport-Security`** only; all other security headers remain on the **bridge** ([ZAP baseline](zap-baseline#header-ownership)).

## ZAP / Nmap with TLS bench

When `OFDD_CADDY_MODE=tls`:

- Nmap: expect **443 open**, 80 may redirect
- ZAP: use `https://<lan-ip>/` (add `-k` trust or import `cert.pem` on the scan workstation)
- PowerShell: `.\Run-OpenFddSecurityScan.ps1 -TargetUrl "https://192.168.204.18"`
- Bash: `./run_openfdd_security_scan.sh --url https://192.168.204.18`

Self-signed certs produce ZAP TLS warnings — expected on OT LAN.

## Renewal

Self-signed certs from `setup_caddy_certs.sh` default to **365 days**. Re-run the script before expiry or bake renewal into site runbooks.

Edge Ansible deploys should document whether the integrator rotates certs manually or via site PKI.

## Secrets

- **Never commit** `key.pem` or production cert bundles
- `workspace/deploy/caddy/certs/` is for local bench only unless your `.gitignore` already excludes generated keys (verify before push)
