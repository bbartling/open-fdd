---
name: local-dev-orchestration
description: "Build and test Open-FDD locally before any Ansible edge deploy. Starts compiled React + bridge on 0.0.0.0:8765 with optional auth roles. Use when deploy=local or before pi_bcn deploy."
---

# Local dev orchestration

## Mandatory gate (before remote deploy)

**Never deploy to `pi_bcn` until local build + tests pass:**

```bash
cd open-fdd
cp workspace/auth.env.example workspace/auth.env.local   # optional, recommended
./scripts/build_and_test.sh
./scripts/run_local.sh start
```

| Step | Command | Pass criteria |
|------|---------|---------------|
| 1 Build | `./scripts/build_and_test.sh` | React → `workspace/api/static/app/`, `pytest tests/workspace_bridge` green |
| 2 Run | `./scripts/run_local.sh start` | `curl http://127.0.0.1:8765/health` → `ok` |
| 3 Auth | login at `http://<host>:8765/login` | operator / integrator / agent from `auth.env.local` |
| 4 Edge | `cd infra/ansible && ./deploy.sh --limit <host>` | only after steps 1–3 |

## Processes

| Process | Port | Bind |
|---------|------|------|
| Bridge (compiled SPA + API) | 8765 | `0.0.0.0` default |
| BACnet commission agent | 8767 | `127.0.0.1` only |
| Vite dev (optional) | 5173 | `./scripts/run_local.sh start --dev` |

## Auth roles (firewall / OT LAN)

See [workspace/deploy/SECURITY.md](../../workspace/deploy/SECURITY.md).

- **operator** — local user, read + ingest
- **integrator** — MSI, BACnet write/release + discover
- **agent** — AI automation, Rule Lab + discover (no writes)

Env file: `workspace/auth.env.local` (loaded by `run_local.sh`).

## Clean restart

```bash
./scripts/run_local.sh stop
pkill -f 'open-fdd|openfdd_bridge|commission_agent' 2>/dev/null || true
./scripts/run_local.sh start
```

## Remote deploy

After local pass — ships **compiled** frontend (not Vite dev):

```bash
./scripts/build_and_test.sh
cd infra/ansible
./deploy.sh --limit bacnet_pi -v
```

Do not use for production bench details — see [ansible-linux-bench-deploy](../ansible-linux-bench-deploy/SKILL.md).

See [references/REFERENCE.md](references/REFERENCE.md).
