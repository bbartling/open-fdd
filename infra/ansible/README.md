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
| `openfdd-bacnet-poll` | RPM → `workspace/bacnet/polls/samples.csv` (systemd edge; local dev uses commission agent poll loop) |
| `openfdd-fdd-loop.timer` | Runs saved Rule Lab rules across the BRICK model every `fdd_loop_interval_hours` → check-engine light |
| `openfdd-feather-retention.timer` | Daily feather prune + GiB cap (`feather_retention_days`, `feather_max_gib`) |
| `caddy` | LAN entry **:80** (or **:443** TLS) → bridge on loopback — default URL with no port |

Poll driver is **off** until `points.csv` is commissioned:

```bash
./deploy.sh --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
./stop_bacnet_polling.sh --limit acme_vm_bbartling
```

## Boss Pi test bench (`192.168.204.12`)

Same host as `vibe_code_apps_12/ansible/inventory.yml` → `bacnet_pi`.

| Fact | Value |
|------|--------|
| Hostname | `bosspi` |
| SSH | `ben@192.168.204.12` |
| CPU | **armv7l** (Pi 3 B+ 32-bit) |
| RAM | ~**1 GB** (not 8 GB — use `ollama_ram_tier: 8gb` only as config label) |

```bash
./deploy.sh --limit bacnet_pi --no-ask-pass -v
```

Check-engine: `http://192.168.204.12/` (Caddy → bridge).

**Ollama / tinyllama:** Official Ollama builds are **arm64 or amd64 only**. Pi 3 B+ with 32-bit Raspbian cannot run Ollama; `ollama_bootstrap.yml` fails fast with a clear message. Use bensserver or a Pi 4/5 with 64-bit OS for AI chat testing.

```bash
# Only on arm64/aarch64 or x86 hosts:
ansible-playbook -i inventory.yml ollama_bootstrap.yml --limit bacnet_pi \
  -e enable_ollama=true -e ollama_ram_tier=8gb \
  -e '{"ollama_model_for_tier":{"8gb":"tinyllama"}}'
```

Services use `Restart=always` and `WantedBy=multi-user.target` so they come back after reboot/power cycle.

**Deploy roadblock on this Pi:** Open-FDD needs **pyarrow** (feather store). There is no prebuilt wheel for **Python 3.13 + armv7l**, and source builds fail on ~1 GB RAM. Use **Pi 4/5 64-bit OS** or deploy to **`acme_vm_bbartling`** for ansible dev testing. Partial sync to bosspi succeeded (code + `points.csv` + venv); systemd units were not installed.

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
./scripts/build_and_test.sh      # vitest + prod UI + pytest (deploy gate)
./scripts/run_local.sh restart   # prod React build + stack + Caddy (if enabled)
# http://127.0.0.1/  — check-engine dashboard (Caddy default, no port)
# http://127.0.0.1:8765/ — direct bridge if OFDD_CADDY_MODE=off
```

UI flags: `--ui-test` (vitest + build), `--ui-skip` (no npm), `--dev` (optional Vite :5173).
