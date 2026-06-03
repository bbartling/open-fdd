# `infra/` — edge deploy and verification

Open-FDD **application code** lives at the repo root (`workspace/`, `open_fdd/`, `scripts/`). **`infra/`** is only **how you ship and verify** that app on remote edges (VM, Pi, bensserver Docker bench).

## Layout

| Path | Purpose |
|------|---------|
| **[ansible/](ansible/README.md)** | Main edge toolkit: inventory, `deploy.sh`, playbooks, host vars, secrets templates |
| **[ansible/Makefile](ansible/Makefile)** | Shortcuts from `infra/ansible/` — `make docker HOST=…`, `make ui-deploy`, etc. |
| **ansible/scripts/** | Shared probes used by deploy and local validate (`http_probes.py`, `bench_operational_verify.sh`, `post_deploy_check.sh`) |

## When to use what

| You are… | Use |
|----------|-----|
| Developing on **bensserver** (Docker bench) | Repo `scripts/` — `run_local.sh`, `openfdd_edge_validate.sh --quick`, `apply_bench_four_points.sh` |
| Deploying to **Acme VM** or **boss Pi** | `cd infra/ansible && ./deploy.sh docker --limit <host>` |
| After deploy smoke test | `./deploy.sh check --limit <host>` or `scripts/post_deploy_check.sh` |
| UI-only push | `make ui-deploy HOST=acme_vm_bbartling` (builds React → bridge static) |

## Makefile (`infra/ansible/Makefile`)

Run from **`infra/ansible/`** (not repo root). It wraps `./deploy.sh`:

- **`make help`** — component list (docker, ui, backend, drivers, …)
- **`make docker HOST=…`** — image bundle + compose on edge
- **`make ui-deploy HOST=…`** — `build_operator_dashboard.sh prod` then rsync static app
- **`make docker-deploy HOST=…`** — `docker_build.sh --save` + docker deploy
- **`make build-test`** — vitest + pytest gate before push

`HOST` defaults to `bacnet_pi`; use `acme_vm_bbartling` for the real-building VM.

## Sites (do not mix)

| Site ID | Where | Poll / model |
|---------|--------|----------------|
| **`demo`** / `bens-office` | Bensserver MSTP bench (device **5007** @ **2000:7**) | Four analog inputs only — see `edge_config/demo/bens-office/points.csv` |
| **`acme`** / `vm-bbartling` | Acme VM deploy (GL36, hundreds of points) | `edge_backup/local/acme/` — separate from bench |

Rule Lab / Plot default to **`demo`** on the bench. A **503** on `/api/model/scope?site_id=acme` means TTL was never synced for Acme on this host — use the correct site or run **Sync TTL** on the Data Model tab.

## Acme VM deploy (bensserver → VM)

Bensserver is the dev source of truth: **commit/push to GitHub when you want a backup on GitHub**; the VM deploy uses **local files on bensserver**, not `git pull` on the server (unless you edited on another machine).

### Full refresh (images + site pack + TTL/SPARQL probes) — **use this most of the time**

```bash
cd ~/open-fdd
./scripts/docker_build.sh --save
./scripts/edge_site_backup.sh acme vm-bbartling   # repo root — snapshots edge pack before push

cd infra/ansible
set -a && source secrets/acme.env.local && set +a

./deploy.sh ops --limit acme_vm_bbartling \
  -e openfdd_docker_sync_workspace_data=false
```

**`ops`** = `deploy_docker` (load images, compose up, push Acme `model.json` / `rules_store.json` / `points.csv` / `commission.env`) + edge maintenance + **POST /api/model/sync-ttl** + SPARQL/feather/log checks.

`openfdd_docker_sync_workspace_data=false` keeps the VM **feather_store**; it does **not** skip the Acme site pack — that still comes from `edge_backup/local/acme/vm-bbartling/`.

### Stack already up after a partial deploy — verify only

```bash
cd ~/open-fdd/infra/ansible
set -a && source secrets/acme.env.local && set +a
./deploy.sh check --limit acme_vm_bbartling
```

### Do **not** chain these after a full `docker` or `ops` (redundant)

| Step | Why skip |
|------|----------|
| `maintain` then `docker` then `ops` | `ops` already runs `deploy_docker` + maintenance |
| `commission` after `docker` / `ops` | `docker` already pushes `points.csv` (commission tag) |
| `docker` then `ops` | Runs the full image deploy **twice** |

Use **either** `docker` **or** `ops`, not both. Prefer **`ops`** when you want TTL sync and health probes in one go.

### Piecemeal (only when you mean it)

| Command | When |
|---------|------|
| `maintain` | Disk prune only; ends with `check` if verify enabled |
| `docker -e openfdd_docker_sync_workspace_data=false` | New images + compose + site pack, no bensserver `workspace/data` tar |
| `commission` | **Only** `points.csv` from edge backup (no image rebuild) |
| `check` | Insurance probes only (Caddy, compose, login, dashboard HTML) |
| `ui` | Dashboard static only (run `build_operator_dashboard.sh prod` first) |

## Docs

- [docs/edge_deploy_docker.md](../docs/edge_deploy_docker.md)
- [docs/edge_deploy.md](../docs/edge_deploy.md)
- [ansible/secrets/README.md](ansible/secrets/README.md)
