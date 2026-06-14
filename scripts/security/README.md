# Open-FDD LAN security scans (ZAP + Nmap)

Passive security smoke for a **single bench host** — run from a laptop on the same LAN as the Open-FDD pentest stack or an Acme edge VM.

Official docs:

- [ZAP baseline expectations](../../docs/security/zap-baseline.md)
- [Release & security testing cycle](../../docs/developer/security-testing.md)
- [TLS and certificate ownership](../../docs/security/tls-and-certs.md)

## What these scripts do

| Script | Platform | Output |
|--------|----------|--------|
| `Run-OpenFddSecurityScan.ps1` | Windows PowerShell | `./openfdd-security-report/` |
| `run_openfdd_security_scan.sh` | macOS / Linux bash | `./openfdd-security-report/` |
| `check_host_security.sh` | Edge VM (Linux) | `05-host-security-check.txt` |
| `check_openfdd_exposure.sh` | Edge VM (Linux) | `06-openfdd-exposure-check.txt` |
| `remediate_ubuntu_host.sh` | Edge VM (Linux) | stdout (dry-run default) |
| `run_maintainer_audits.sh` | Maintainer workstation | CI parity audits |

Each run (by default) **deletes and recreates** `openfdd-security-report/` with:

1. **curl** reachability + response headers (GET, not HEAD)
2. **OWASP ZAP baseline** (passive — Docker `ghcr.io/zaproxy/zaproxy:stable`)
3. **Nmap** scoped service + HTTP header scripts on one host IP
4. Text summaries and a review checklist

**Not included:** ZAP full/active scan, authenticated dashboard/API crawl (see [Authenticated scanning](../../docs/security/authenticated-scanning.md)).

## Prerequisites

### Windows

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) — running before ZAP
2. [Nmap](https://nmap.org/download.html) — `winget install -e --id Insecure.Nmap`
3. PowerShell 5.1+ (built into Windows)

### macOS

```bash
brew install --cask docker    # or Docker Desktop from docker.com
brew install nmap
```

Start Docker Desktop before running ZAP.

### Linux

```bash
# Docker (distro packages or docker.com)
sudo apt install nmap    # Debian/Ubuntu
```

Ensure your user can run `docker` without sudo.

## On the Open-FDD host first

Start the production-like pentest stack (Caddy `:80` → bridge loopback `:8765`):

```bash
cd open-fdd
./scripts/pentest_production_stack.sh start
./scripts/pentest_production_stack.sh verify
```

ZAP target is usually **`http://<lan-ip>/`** (not `:8765`).

## Run from a LAN workstation

### Windows (default benserver example)

```powershell
cd open-fdd\scripts\security
.\Run-OpenFddSecurityScan.ps1
```

Custom host:

```powershell
.\Run-OpenFddSecurityScan.ps1 -HostIp "192.168.204.18" -TargetUrl "http://192.168.204.18"
```

SSH tunnel to bridge only (debug):

```powershell
ssh -L 8765:127.0.0.1:8765 user@192.168.204.18
.\Run-OpenFddSecurityScan.ps1 -HostIp "192.168.204.18" -TargetUrl "http://127.0.0.1:8765"
```

### macOS / Linux

```bash
cd open-fdd/scripts/security
./run_openfdd_security_scan.sh --host 192.168.204.18 --url http://192.168.204.18
```

## Read results first

| File | Content |
|------|---------|
| `40-release-gate-summary.txt` | **SECURITY GATE** — asset leak scan + auth probe |
| `90-quick-findings-summary.txt` | One-page overview |
| `30-nmap-findings-summary.txt` | Port exposure |
| `31-zap-findings-summary.txt` | ZAP alert snippets |
| `99-review-checklist.txt` | What to fix vs accept |
| `02-web-response-headers.txt` | Raw HTTP headers from curl |

## Expected posture (Caddy HTTP bench)

| Port | Expected from LAN |
|------|-------------------|
| 80 | open (Caddy) |
| 443 | closed or open if TLS mode |
| 8765 | **closed** (bridge loopback) |
| 5173 | **closed** (no dev Vite) |
| 8090 | closed/filtered (mcp-rag internal) |

## Release gate (production bundle)

CI and local builds run `scripts/check_production_assets.py` after `npm run build`. It fails if shipped JS/CSS contains private LAN IPs (`192.168.*`, `10.*`, `172.16–31.*`), bench Niagara defaults, or `ws://` URLs. Harmless library strings (`localhost`, `127.0.0.1`, W3C namespace URLs) are allowlisted.

PowerShell scan enforces the same against the live target (`40-release-gate-summary.txt`) and **fails the gate** when:

- ZAP exits nonzero or reports are missing
- ZAP JSON contains High alerts (Medium = warn unless `-StrictZap`)
- Anonymous callers reach protected `/api/*` routes with 2xx
- Production JS bundle contains private LAN literals

**Authenticated ZAP (recommended):** pass integrator creds without logging secrets:

```powershell
.\Run-OpenFddSecurityScan.ps1 -AuthEnvFile "C:\path\to\auth.env.local"
# or: $env:OFDD_INTEGRATOR_USER / $env:OFDD_INTEGRATOR_PASSWORD in the shell
```

ZAP Bearer injection uses `docker --env-file` + `32-zap-replacer.prop` (not fragile `-z` token splitting). Confirm `31-zap-findings-summary.txt` shows `Auth injected: True`.

## Accepted ZAP findings (3.0.4+)

- CSP `style-src 'unsafe-inline'` (Medium) — Vite/React; documented TODO
- Missing COEP (Low) — intentionally omitted

**Fixed in 3.0.4:** duplicate `Referrer-Policy`, conflicting `X-Frame-Options`, stacked `Server` banners.

## When to run

Part of every **patch release** before Acme deploy:

1. Local pytest + `bench_5007_arrow_battery.sh`
2. `pentest_production_stack.sh verify`
3. **This scan** from a LAN PC
4. GitHub CI + CodeRabbit on PR
5. After GHCR publish → Acme `post_deploy_check.sh --full`

See [Developer: security testing cycle](../../docs/developer/security-testing.md).

## Tenable / Nessus (IT scan follow-up)

After an IT vulnerability scan on an edge VM:

```bash
# On the edge host (SSH)
./check_host_security.sh
./check_openfdd_exposure.sh --edge-ip <lan-ip>
./remediate_ubuntu_host.sh              # dry-run
./remediate_ubuntu_host.sh --apply      # apt full-upgrade (maintenance window)
```

Docs: [Tenable remediation](../../docs/security/tenable-remediation.md), [Linux host hardening](../../docs/security/linux-host-hardening.md).

## Safety

- **Baseline only** — passive ZAP, not full active scan
- **One host** — do not scan OT BACnet subnets or controllers
- **Bench / fake sites** — authenticated deep scans only on test stacks with approval
- **Host remediation** — `remediate_ubuntu_host.sh` does not change firewall rules; reboot only with `--reboot-if-needed`
