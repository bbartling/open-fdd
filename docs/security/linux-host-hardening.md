---
title: Linux host hardening
parent: Security
nav_order: 7
---

# Linux host hardening

Generic **Ubuntu edge VM** guidance for Open-FDD deployments scanned by IT tools (Tenable/Nessus, Qualys, etc.). This complements application-level [LAN hardening]({% link security/lan-hardening.md %}) and [TLS]({% link security/tls-and-certs.md %}).

Nessus-specific finding tables: [Tenable remediation]({% link security/tenable-remediation.md %}).

## Scope

| Layer | Owner | Repo support |
|-------|-------|--------------|
| Ubuntu kernel, OpenSSH, apt packages | **Site IT / integrator** | `scripts/security/remediate_ubuntu_host.sh` |
| Docker engine, compose, Caddy | **Integrator** | Ansible + `check_openfdd_exposure.sh` |
| Open-FDD containers (pip/pyOpenSSL) | **Open-FDD maintainers** | `docker/python-security-constraints.txt`, GHCR images |
| Self-signed TLS on OT LAN | **Expected lab finding** | Enterprise CA path in [TLS]({% link security/tls-and-certs.md %}) |

## Quick operator workflow

On the edge VM (SSH):

```bash
cd ~/open-fdd
./scripts/security/check_host_security.sh
./scripts/security/check_openfdd_exposure.sh --edge-ip "$(hostname -I | awk '{print $1}')"
```

Remediate host OS (maintenance window):

```bash
./scripts/security/remediate_ubuntu_host.sh          # dry-run
sudo ./scripts/security/remediate_ubuntu_host.sh --apply
# if /var/run/reboot-required exists:
sudo reboot
./scripts/security/check_host_security.sh
```

Pull new Open-FDD images after a release that pins container pip/pyOpenSSL:

```bash
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit <inventory_host>
```

## Ubuntu version and EOL

Supported targets: **Ubuntu 22.04 LTS** or **24.04 LTS** (64-bit). Rebuild hosts still on **16.04** or **18.04** — `apt upgrade` cannot clear an SEoL finding.

Validate a surprising 16.04 Nessus hit:

```bash
lsb_release -a
cat /etc/os-release
# Scan credential / stale DNS / container banner mismatch?
```

## Kernel and package updates

```bash
sudo apt update
sudo apt full-upgrade -y
uname -r
test -f /var/run/reboot-required && echo "reboot required"
sudo reboot   # maintenance window
```

Optional status tools:

```bash
ubuntu-security-status    # or: pro status
apt list --upgradable | grep -i security
```

## Host Python (pip, wheel, pyOpenSSL)

Tenable often reports **host** `pip`, `wheel`, and `pyOpenSSL` versions installed by Ubuntu packages or admin `pip install`. Prefer **apt** on the host:

```bash
python3 -m pip show pip setuptools wheel pyOpenSSL
sudo apt install --only-upgrade python3-pip python3-openssl python3-wheel
```

Open-FDD **containers** pin toolchain versions at image build — see `docker/python-security-constraints.txt`. Rescan after `docker compose pull`.

## Ollama — no LAN exposure

Ollama has **no built-in authentication** in typical deployments. Treat LAN exposure as **Critical**.

| Rule | Implementation |
|------|----------------|
| Bind loopback only | `OLLAMA_HOST=127.0.0.1:11434` in systemd (`ollama.service`) or dev bootstrap |
| Bridge calls server-side | `OFDD_OLLAMA_BASE_URL=http://127.0.0.1:11434` or `host.docker.internal:11434` from containers |
| Never publish `:11434` on `0.0.0.0` | Compose uses `127.0.0.1:11434:11434` when Docker Ollama is enabled |

Validation:

```bash
ss -tulpn | grep 11434
curl -sf http://127.0.0.1:11434/api/tags | head
curl -sf --max-time 3 http://<edge-lan-ip>:11434/api/tags   # must FAIL from another host
```

Firewall (if management host needs GPU Ollama — rare):

```bash
# Example: block LAN → 11434; allow loopback only (adjust interface names)
sudo ufw deny 11434/tcp
sudo ufw allow from 127.0.0.0/8 to any port 11434 proto tcp
```

## OpenSSH Terrapin (CVE-2023-48795)

Apply Ubuntu security updates first (`openssh-server`, `openssh-client`). Verify:

```bash
ssh -V
sudo sshd -T | grep -Ei '^(ciphers|macs|kexalgorithms)'
```

Manual algorithm hardening is **optional** and can lock out clients — document rollback (`sshd_config.bak`) before changes. Do not automate cipher stripping in repo scripts.

## ICMP timestamp (Low)

Nessus may report ICMP timestamp disclosure. Optional hardening at host firewall or upstream network — low priority for isolated OT VLANs.

Example (nftables — site-specific):

```bash
# Block ICMP timestamp / type 13 — verify with IT before applying
sudo nft add rule inet filter input icmp type timestamp-request drop
```

## TLS and certificate scans

Self-signed or internal CA certificates produce **Medium** Nessus SSL findings (untrusted, self-signed, expiry). That is **expected** for lab/OT encryption-in-transit. For clean SSL plugin results, install a **site enterprise CA** certificate on Caddy — [TLS and certificates]({% link security/tls-and-certs.md %}#enterprise-ca-production).

## Maintainer security audits (CI parity)

```bash
./scripts/security/run_maintainer_audits.sh
```

Matches GitHub Actions `operator-bridge-security` job where possible.
