---
title: Tenable / Nessus remediation
parent: Security
nav_order: 8
---

# Tenable / Nessus remediation

Remediation plan for **IT/Tenable.io Nessus** findings on an Open-FDD **OT/LAN edge** deployment (e.g. Acme GL36 lab VM). Open-FDD runs behind a building firewall on Ubuntu with Docker Compose, Caddy, and optional host Ollama.

Related: [Linux host hardening]({{ "/security/linux-host-hardening/" | relative_url }}), [TLS and certificates]({{ "/security/tls-and-certs/" | relative_url }}), [LAN hardening]({{ "/security/lan-hardening/" | relative_url }}), [Security testing cycle]({{ "/developer/security-testing/" | relative_url }}).

## Prioritized action plan

| Priority | Action | Owner |
|----------|--------|-------|
| **P0** | Confirm Ubuntu is **not** 16.04/18.04; rebuild if EOL | IT / integrator |
| **P0** | Bind Ollama to **127.0.0.1** only; verify LAN cannot reach `:11434` | Integrator |
| **P0** | `apt full-upgrade` + **reboot** for kernel USNs (8254, 8278, 8373) | IT / integrator |
| **P1** | Upgrade host `pip`/`wheel`/`pyOpenSSL` via apt or documented pip path | IT / integrator |
| **P1** | Pull GHCR images built with `docker/python-security-constraints.txt` | Integrator |
| **P2** | OpenSSH packages current; review Terrapin after patch | IT |
| **P2** | TLS: accept self-signed findings **or** install enterprise CA cert | IT decision |
| **P3** | ICMP timestamp: optional firewall rule | Network / IT |

## Finding classification table

| Nessus finding | Severity | Class | Remediation |
|----------------|----------|-------|-------------|
| Canonical Ubuntu Linux SEoL (16.04.x) | Critical | Host OS / **false positive?** | `lsb_release -a` — rebuild VM on 24.04 LTS if truly 16.04; if host is 22.04/24.04, check scan target IP, credentials, stale asset record |
| Ollama Unauthenticated Access | Critical | Deployment config | `OLLAMA_HOST=127.0.0.1:11434`; no `0.0.0.0:11434`; firewall deny; see [Ollama](#ollama-unauthenticated-access-critical) |
| Ubuntu kernel USN-8254-1 | Critical | Host OS | `sudo apt update && sudo apt full-upgrade -y && sudo reboot` |
| pyOpenSSL 22.0.x &lt; 26.0.0 Buffer Overflow | Critical | Host pip **and** container | Host: `apt upgrade python3-openssl` or pip ≥26; Container: GHCR image with constraints file |
| Ubuntu pip USN-8344-1 | High | Host OS + container build | `apt full-upgrade`; image build upgrades `pip>=26` |
| SSL Certificate Cannot Be Trusted | Medium | **Accepted risk** (lab) / deployment | Self-signed Caddy — use enterprise CA for clean scan |
| SSL Self-Signed Certificate | Medium | **Accepted risk** (lab) | Same as above |
| SSL Certificate Expiry | Medium | Deployment / monitoring | `openssl x509 -dates`; renew `setup_caddy_certs.sh` or site PKI |
| SSH Terrapin (CVE-2023-48795) | Medium | Host OS | Upgrade `openssh-server`; validate `ssh -V` |
| Ubuntu wheel USN-8221-1 | Medium | Host OS | `apt full-upgrade` |
| Ubuntu kernel USN-8278-1, USN-8373-1 | Medium | Host OS | `apt full-upgrade` + reboot |
| pyOpenSSL 0.14.x Security Bypass | Medium | Host + container | Same as pyOpenSSL Critical — upgrade to ≥26 |
| ICMP Timestamp Request | Low | Network / optional host | Firewall drop; often accepted on isolated OT VLAN |

**Class legend:** (1) repo-owned fix · (2) Docker base/image · (3) host OS · (4) deployment/config · (5) accepted risk · (6) validate false positive

## Operator commands (edge VM)

### Validate (read-only)

```bash
cd ~/open-fdd
./scripts/security/check_host_security.sh
./scripts/security/check_openfdd_exposure.sh --edge-ip "$(hostname -I | awk '{print $1}')"
lsb_release -a
uname -r
test -f /var/run/reboot-required && cat /var/run/reboot-required.pkgs
python3 -m pip show pip setuptools wheel pyOpenSSL 2>/dev/null | grep -E '^(Name|Version):'
ss -tulpn | grep -E ':80|:443|:8765|:11434'
curl -sf http://127.0.0.1:11434/api/tags | head -3
```

From a **different LAN workstation** (must fail):

```bash
curl -sf --max-time 3 http://<edge-ip>:11434/api/tags
```

### Remediate host (maintenance window)

```bash
./scripts/security/remediate_ubuntu_host.sh              # dry-run
./scripts/security/remediate_ubuntu_host.sh --apply
sudo reboot    # if reboot-required
./scripts/security/check_host_security.sh
```

### Remediate Open-FDD containers

```bash
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit <inventory_host>
docker compose pull && docker compose up -d
```

### Rescan

After reboot and image pull, request IT **Nessus rescan** of the edge IP. Compare plugin output to the table above.

## Ollama unauthenticated access (Critical)

**Not an Open-FDD code bug** — Ollama’s API is unauthenticated by design. Risk is **network exposure**.

Repo defaults (3.0.5+):

- Systemd: `Environment=OLLAMA_HOST=127.0.0.1:11434` in `infra/ansible/templates/ollama.service.j2`
- Compose Ollama (optional profile): `127.0.0.1:11434:11434` only
- Acme-style edge: host Ollama + bridge via `host.docker.internal:11434` (container → host loopback path)
- `post_deploy_check.sh` warns if `:11434` listens on `0.0.0.0`

Re-apply Ansible Ollama unit after upgrade:

```bash
ansible-playbook -i inventory.yml ollama_bootstrap.yml --limit <host> -e enable_ollama=true
```

## pyOpenSSL and pip in containers

Docker build installs `docker/python-security-constraints.txt` before application requirements:

- `pip>=26.0`, `setuptools>=75.0`, `wheel>=0.45`
- `pyOpenSSL>=26.0.0`, `cryptography>=44.0.0`

CI `pip-audit` runs against bridge + bacnet requirements with the same constraints.

## TLS — expected vs production

| Mode | Nessus SSL plugins | When to use |
|------|-------------------|-------------|
| Caddy HTTP `:80` | No TLS plugins | Dev / HTTP-only VLAN |
| Caddy self-signed `:443` | Medium: untrusted, self-signed, expiry | OT LAN encryption, lab |
| Enterprise CA cert on Caddy | Clean SSL plugins (if chain trusted) | IT mandates clean Nessus |

See [TLS — enterprise CA]({{ "/security/tls-and-certs/" | relative_url }}#enterprise-ca-on-caddy-edge).

## Residual findings after remediation

Even with a patched host and loopback-only Ollama, IT may still see:

- **SSL** Medium on self-signed TLS (accepted for lab; document in risk register)
- **ICMP** Low (optional network block)
- **Container** plugins if Nessus scans Docker overlay networks — clarify scan scope with IT

## Notes for IT / security team

1. Scan the **edge VM IP**, not individual container IPs, unless container CVE correlation is required.
2. Open-FDD **bridge :8765** should be **loopback-only**; LAN entry is **Caddy :80/:443**.
3. **BACnet UDP 47808** on commission is expected OT traffic — out of scope for web/plugin remediation.
4. Do not expose Ollama **11434** to the building LAN; agent chat is server-side only.
5. Kernel CVEs require **host reboot** — schedule with operations.
6. For authenticated web/API depth, see roadmap [Authenticated scanning]({{ "/security/authenticated-scanning/" | relative_url }}).

## Repo-owned fixes (this document’s release)

| Item | Location |
|------|----------|
| Container pip/pyOpenSSL pins | `docker/python-security-constraints.txt`, `docker/Dockerfile` |
| Ollama loopback systemd | `infra/ansible/templates/ollama.service.j2` |
| Host/exposure check scripts | `scripts/security/check_*.sh`, `remediate_ubuntu_host.sh` |
| Post-deploy Ollama bind warn | `infra/ansible/scripts/post_deploy_check.sh` |
| CI pip-audit + constraints | `.github/workflows/ci.yml` |
