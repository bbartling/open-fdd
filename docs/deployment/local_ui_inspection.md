# Local UI inspection (no long validation)

Use this path when you want to **click around the dashboard** — login, tabs, JSON/CSV mode — without running 1-hour or 6-hour FDD validation.

## Quick start (Linux)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
git checkout integration/ui-inspection-build   # or merge PR when ready

chmod +x scripts/openfdd_inspection_build.sh
./scripts/openfdd_inspection_build.sh --build --smoke
```

Open **http://127.0.0.1:8080**

## Credentials

| File | Purpose |
| --- | --- |
| `workspace/auth.env.local` | **Bcrypt hashes only** — do not paste these as login passwords |
| `workspace/bootstrap_credentials.once.txt` | **Plaintext passwords** (one-time handoff, gitignored) |

If login fails with “invalid credentials”, you are probably using a hash. Run:

```bash
./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart
```

Save the printed passwords (or `bootstrap_credentials.once.txt`), then delete the handoff file when done.

Default users: `operator` (read-only), `integrator`, `agent`.

## JSON/CSV-only mode (no BACnet/Modbus hardware)

```bash
./scripts/openfdd_inspection_build.sh --desktop --smoke
```

Equivalent env:

```bash
OPENFDD_BACNET_ENABLED=0
OPENFDD_MODBUS_ENABLED=0
OPENFDD_HAYSTACK_ENABLED=0
OPENFDD_JSON_API_ENABLED=1
OPENFDD_IMPORT_ENABLED=1
OPENFDD_EXPORT_ENABLED=1
```

BACnet and Modbus tabs should show **disabled / not configured**, not red 500 errors.

## Manual smoke (optional)

```bash
OPENFDD_BRIDGE_BASE=http://127.0.0.1:8080 ./scripts/openfdd_auth_smoke.sh
OPENFDD_API_BASE=http://127.0.0.1:8080 ./scripts/openfdd_ui_smoke.sh
```

Artifacts: `workspace/logs/ui_smoke_<timestamp>/`

## Pages to click

| Route | Tab |
| --- | --- |
| `/` | Building status (public) |
| `/login` | Sign in |
| `/bacnet` | BACnet |
| `/modbus` | Modbus |
| `/haystack` | Haystack |
| `/json-api` | JSON API |
| `/model` | Data model |
| `/sql-fdd` | SQL FDD rules |
| `/plot` | Trend plot |
| `/reports` | Report builder |
| `/data-management` | Data management |

## What this pass intentionally skips

- 1-hour live FDD validation
- 6-hour validation
- CSV append/delete proof
- PDF quality validation
- Live BACnet / Modbus hardware

Those are a **follow-up pass** after UI inspection is satisfactory.

## See also

- [local-dev.md](./local-dev.md) — all build recipes (localhost, Caddy TLS, auth)
- [local_ui_build.md](./local_ui_build.md) — GHCR vs local Dockerfile paths
- [windows_docker_desktop.md](./windows_docker_desktop.md) — Docker Desktop on Windows
- [caddy.md](./caddy.md) — Caddy ingress details

## Remote HTTPS (production-like bench access)

After local image build:

```bash
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip 192.168.204.55
```

Open **https://192.168.204.55/** from another machine (accept self-signed cert). Full recipe: [local-dev.md](./local-dev.md).
