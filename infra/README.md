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

## Acme VM deploy (recommended sequence)

Run from **repo root** for backup; run **deploy** from `infra/ansible/`.

```bash
cd ~/open-fdd
./scripts/docker_build.sh --save
./scripts/edge_site_backup.sh acme vm-bbartling    # local pack snapshot (not ./scripts/ under ansible/)

cd infra/ansible
set -a && source secrets/acme.env.local && set +a

# One shot: images + compose + site model/rules/points + maintenance + TTL/SPARQL probes
./deploy.sh ops --limit acme_vm_bbartling \
  -e openfdd_docker_sync_workspace_data=false

# Or stepwise (what you ran):
# ./deploy.sh maintain --limit acme_vm_bbartling
# ./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_sync_workspace_data=false
# ./deploy.sh check --limit acme_vm_bbartling    # insurance only (after docker is up)
```

`openfdd_docker_sync_workspace_data=false` keeps the VM’s **feather_store** and does not overwrite with bensserver `workspace/data`. The docker playbook still pushes **Acme** `model.json`, `rules_store.json`, and `points.csv` from `edge_backup/local/acme/vm-bbartling/` (or `edge_config/acme/`).

If `maintain` failed on “Illegal option -o pipefail”, pull latest `develop` (shell tasks now use `/bin/bash`) and re-run `./deploy.sh check --limit acme_vm_bbartling`.

## Docs

- [docs/edge_deploy_docker.md](../docs/edge_deploy_docker.md)
- [docs/edge_deploy.md](../docs/edge_deploy.md)
- [ansible/secrets/README.md](ansible/secrets/README.md)
