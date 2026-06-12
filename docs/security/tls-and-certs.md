---
title: TLS and certificates
parent: Security
nav_order: 3
---

# TLS and certificates

Who generates, stores, and renews TLS material for Open-FDD on OT LANs — and how that ties into ZAP/Nmap bench testing.

Developer release cycle: [Security testing cycle]({{ "/developer/security-testing/" | relative_url }}).

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

Caddy serves `:443` and redirects `:80` → HTTPS. Caddy adds **`Strict-Transport-Security`** only; all other security headers remain on the **bridge** ([ZAP baseline]({{ "/security/zap-baseline/" | relative_url }}#header-ownership)).

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

## Enterprise CA on Caddy (edge)

When IT requires **clean Nessus SSL plugins** (no self-signed / untrusted chain), install a site-provided certificate on the edge VM instead of `setup_caddy_certs.sh` output.

Typical layout (Ansible / manual):

```text
/etc/openfdd/caddy/cert.pem   # full chain (leaf + intermediates)
/etc/openfdd/caddy/key.pem    # private key (0600, root or caddy user)
```

Ansible TLS mode (`caddy_mode: tls`) already points Caddy at those paths — see `infra/ansible/templates/Caddyfile.j2`.

**Internal enterprise CA workflow:**

1. Generate CSR on the edge host or request cert from site PKI for the operator hostname (e.g. `openfdd.acme.local`).
2. Install `cert.pem` + `key.pem` under `/etc/openfdd/caddy/`.
3. Distribute the **CA root** to admin laptops (trust store) so browsers and ZAP scans validate the chain.
4. Monitor expiry:

```bash
openssl x509 -in /etc/openfdd/caddy/cert.pem -noout -dates
```

**Caddyfile snippet (TLS, enterprise cert):**

```text
:443 {
    tls /etc/openfdd/caddy/cert.pem /etc/openfdd/caddy/key.pem
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }
    reverse_proxy 127.0.0.1:8765
}
```

Lab/self-signed mode still produces expected **Medium** Tenable findings — document as accepted risk or switch to enterprise CA. See [Tenable remediation]({{ "/security/tenable-remediation/" | relative_url }}).

## Caddy internal CA mode (lab)

`./scripts/setup_caddy_certs.sh` generates a **self-signed** pair for bench TLS. Trust `cert.pem` on scan workstations (`-k` curl, ZAP import) or accept browser warnings. Not suitable when IT mandates trusted chains.

## Secrets

- **Never commit** `key.pem` or production cert bundles
- `workspace/deploy/caddy/certs/` is for local bench only unless your `.gitignore` already excludes generated keys (verify before push)
