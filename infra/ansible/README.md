# Ansible edge deploy (Open-FDD)

Same workflow as `vibe_code_apps_12/ansible`: inventory → `./deploy.sh --limit <host>`.

## Quick start

```bash
cd infra/ansible
cp inventory.example.yml inventory.yml          # set real IPs (gitignored)
cp host_vars/bacnet_pi.yml.example host_vars/bacnet_pi.yml
cp host_vars/acme_vm_bbartling.yml.example host_vars/acme_vm_bbartling.yml

export SSHPASS='...'   # Acme VM if password auth
./deploy.sh --limit bacnet_pi -v
./deploy.sh --limit acme_vm_bbartling -v
```

## Services on edge

| Unit | Role |
|------|------|
| `openfdd-bridge` | FastAPI Rule Lab + FDD + ingest (8765) |
| `openfdd-bacnet-commission` | Discover jobs HTTP agent (8767) |
| `openfdd-bacnet-poll` | RPM → `workspace/bacnet/polls/samples.csv` |
| `openfdd-fdd-loop.timer` | Runs saved Rule Lab rules across the BRICK model every `fdd_loop_interval_hours` → check-engine light |
| `openfdd-feather-retention.timer` | Daily feather store prune/compact (`feather_retention_days`) |
| `caddy` | LAN entry **:80** (or **:443** TLS) → bridge on loopback — default URL with no port |

Poll driver is **off** until `points.csv` is commissioned:

```bash
./deploy.sh --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
./stop_bacnet_polling.sh --limit acme_vm_bbartling
```

## vs vibe_code_apps_12

| vibe12 | open-fdd |
|--------|----------|
| MQTT → AWS IoT | Local CSV → `POST /ingest/bacnet` → feather |
| `vibe12-bacnet-read` | `openfdd-bacnet-poll` |
| Cloud Lambda dashboard | Edge bridge + optional Caddy |
| `commissioning_web` on bensserver | Bridge `/bacnet` + commission agent |

## Auth

Set in private `host_vars`:

```yaml
ofdd_auth_secret: "long-random"
ofdd_web_user: operator
ofdd_web_password: "..."
```

Or set `caddy_mode: tls` in group_vars for self-signed HTTPS on OT LAN.

Check-engine dashboard (`/` and `/faults`) is **public read-only** — no login required.
Optional bridge auth (`ofdd_auth_secret`) gates Rule Lab, BACnet writes, etc.

## Local dev (bensserver)

```bash
./scripts/run_local.sh
# http://127.0.0.1/  check-engine dashboard (Caddy default, no port)
```
