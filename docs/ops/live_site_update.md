---
title: Live site update (SSH)
parent: Operations
nav_order: 1
---

# Live site update (SSH)

Use this runbook when a **live edge VM** already has a minimal deploy folder and you are **not** doing `git pull` on the host.

Typical layout (no full git checkout):

```text
/home/bbartling/open-fdd/
  docker/
  docker-compose.yml
  workspace/
```

`workspace/` is the **live site state** — BACnet commissioning files, poll CSV, feather historian, BRICK model, FDD rules, MCP RAG index, and env files. Image upgrades must **preserve** it.

## Concepts (plain language)

| Term | Meaning |
|------|---------|
| **Container** | A running app instance (bridge, commission, mcp-rag). Recreated on upgrade. |
| **Image** | Downloaded app package from GHCR (e.g. `openfdd-bridge:2026.06.07-edge`). |
| **Docker volume** | Persistent data Docker manages separately. This minimal layout uses **bind mounts** into `workspace/` instead. |
| **`workspace/`** | Open-FDD site state on disk. **This is what you must not lose.** |

{: .warning }
> **Never on live sites:** `docker compose down -v`, `docker volume prune`, `docker system prune -a --volumes`, or `docker rm -f $(docker ps -aq)`. Those can destroy data or leave the site down with no rollback path.

## Before you start

1. Maintenance window or low-traffic period (containers restart briefly).
2. SSH access to the edge host.
3. New GHCR tag published (check [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge)).
4. Optional: control machine with the full `open-fdd` repo for [post-deploy check](#control-machine-insurance-check).

## 1. Backup `workspace/`

Container processes may write files as **`root:root`** with mode **`0600`**. A normal user `tar` can fail on those paths — use `sudo`:

```bash
cd /home/bbartling/open-fdd

export BACKUP_ROOT="$HOME/openfdd-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_ROOT"

cp docker-compose.yml "$BACKUP_ROOT/docker-compose.yml.before"

docker compose ps > "$BACKUP_ROOT/docker-compose-ps-before.txt"
docker compose config --images > "$BACKUP_ROOT/docker-images-before.txt"

sudo tar --xattrs --acls -czf "$BACKUP_ROOT/workspace-full.tgz" workspace
sudo chown "$USER:$USER" "$BACKUP_ROOT/workspace-full.tgz"

echo "Backup saved to: $BACKUP_ROOT"
du -h "$BACKUP_ROOT/workspace-full.tgz"
```

## 2. Verify new images exist on GHCR

```bash
export NEW_TAG="2026.06.07-edge"

docker manifest inspect ghcr.io/bbartling/openfdd-bridge:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-commission:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG} >/dev/null &&
echo "All images exist for ${NEW_TAG}"
```

Replace `NEW_TAG` with the tag you intend to deploy.

## 3. Update the React UI bundle (required for dashboard changes)

{: .warning }
> **Image pull alone does not update the browser UI.** The bridge serves
> `workspace/api/static/app/` from the **bind mount first**, before anything baked
> into the GHCR image (`static_dashboard_dir()` in the bridge). If that folder still
> has an old `index-*.js` hash (e.g. `index-TRH4YIfA.js`), you will keep seeing the
> old BACnet tree, Host Stats revisions panel, Model & assignments tab, etc.

**From bensserver (control machine, full repo):**

```bash
cd /path/to/open-fdd
./scripts/build_operator_dashboard.sh prod
cd infra/ansible
./deploy.sh ui --limit acme_vm_bbartling
```

Confirm the edge picked up the new hash:

```bash
curl -sf http://<edge-ip>/ | grep -o 'index-[^"]*\.js' | head -1
# Should match bensserver: grep -o 'index-[^"]*\.js' workspace/api/static/app/index.html
```

**One command (recommended after CI publishes a new tag):**

```bash
OPENFDD_IMAGE_TAG=2026.06.08-edge ./scripts/upgrade_edge_full.sh --limit acme_vm_bbartling
```

That runs: dashboard build → `deploy.sh ui` → GHCR pull + `docker compose up -d --force-recreate` → `post_deploy_check.sh --full`.

## 4. Update `docker-compose.yml` and recreate containers

Edit image tags in `docker-compose.yml` (example: `2026.06.04-edge` → `2026.06.07-edge`):

```bash
cd /home/bbartling/open-fdd

cp docker-compose.yml "$BACKUP_ROOT/docker-compose.yml.before-tag-change"
sed -i "s/2026\.06\.04-edge/${NEW_TAG}/g" docker-compose.yml

docker compose config --images
docker compose pull
docker compose up -d --force-recreate

docker compose ps
```

Bind-mounted `workspace/` is unchanged; only container images restart.

## 5. On-VM smoke checks

```bash
cd ~/open-fdd

echo "=== Stack ==="
docker compose ps
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

echo "=== Bridge health ==="
curl -sf http://127.0.0.1:8765/health | jq . || curl -sf http://127.0.0.1:8765/health

echo "=== Stack health (if available — may require auth) ==="
curl -i http://127.0.0.1:8765/health/stack

echo "=== MCP health from inside mcp-rag container ==="
docker compose exec mcp-rag sh -lc 'curl -sf http://127.0.0.1:8090/health || wget -qO- http://127.0.0.1:8090/health || python - <<PY
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=5).read().decode())
PY'

echo "=== BACnet samples still moving ==="
ls -lah workspace/bacnet/polls/samples.csv
tail -n 1 workspace/bacnet/polls/samples.csv

echo "=== BACnet ingest state ==="
sudo cat workspace/data/bacnet_ingest_state.json | jq . || sudo cat workspace/data/bacnet_ingest_state.json

echo "=== Feather store retained and writing ==="
du -sh workspace/data/feather_store
find workspace/data/feather_store -type f -printf "%TY-%Tm-%Td %TH:%TM %p\n" | sort | tail -n 10

echo "=== Recent log errors ==="
docker compose logs --since 20m | grep -Ei "error|exception|traceback|critical|failed|permission|denied" || true
```

**`/health/stack` nuance:** `/health` should return `200` without auth. `/health/stack` may return `401`, `403`, `404`, or an empty body depending on auth settings — use `curl -i` (not `curl -sf`) so you see the status code. A failed silent `curl -sf` does not mean the stack is broken.

### Arrow / FDD rules (Open-FDD 3.0+)

All saved rules use `apply_faults_arrow(table, cfg, context)` on PyArrow tables.

From bensserver:

```bash
./scripts/validate_fdd_backends.sh --docker   # must exit 0
```

On the edge VM after upgrade:

```bash
grep -R "apply_faults_arrow" -n workspace/data/rules_py 2>/dev/null | wc -l
docker compose exec bridge python3 -c "
from openfdd_bridge.rule_store import RuleStore
from open_fdd.arrow_runtime.rules import detect_rule_backend
from openfdd_bridge.rule_source import read_source
for r in RuleStore().list_rules():
    if not r.get('enabled', True): continue
    code = read_source(r.get('source_path','')) or r.get('code','')
    print(r.get('name'), detect_rule_backend(code, r))
"
```

Spot-check **Rule Lab** quick-test shows `backend: arrow`.

## 6. Control-machine insurance check

From your laptop or bensserver (full repo clone, not on the edge VM):

```bash
cd /path/to/open-fdd/infra/ansible

./scripts/post_deploy_check.sh --limit acme_vm_bbartling

# Or explicitly:
./scripts/post_deploy_check.sh --host 100.122.106.124 --ssh-user bbartling
```

This is the recommended **non-destructive** check: Caddy → React dashboard, `/health/stack`, MCP, BACnet tree, BRICK/SPARQL, Docker log scan.

{: .warning }
> **Do not run on live commissioned sites:** `openfdd_edge_validate.sh --full` or `acme_operational_verify.sh` — those rediscover BACnet and reset bench model/rules.

## 7. Browser validation

Open the site via **Caddy on port 80** (e.g. `http://<tailscale-or-lan-ip>/`), not only `127.0.0.1:8765`:

1. View page source / Network — confirm **new** `index-*.js` hash (not the pre-upgrade bundle).
2. Home / faults dashboard loads.
3. Integrator login (`workspace/auth.env.local`).
4. **Host stats** — container image tag / git sha (3.0+ bridge).
5. **BACnet** — right-click point → **Refresh PV**, **Read priority array**.
6. **Model & assignments** (`/model`) — commissioning JSON export (404 = bridge image + UI both stale).
7. Rule Lab — quick-test a saved rule (`backend: arrow`).

## Rollback

If the new tag misbehaves, restore the previous tag in compose and recreate:

```bash
cd /home/bbartling/open-fdd

# Example: roll back from 2026.06.07-edge to 2026.06.04-edge
export NEW_TAG="2026.06.07-edge"
export OLD_TAG="2026.06.04-edge"

sed -i "s/${NEW_TAG}/${OLD_TAG}/g" docker-compose.yml

docker compose pull
docker compose up -d --force-recreate

docker compose ps
curl -sf http://127.0.0.1:8765/health | jq . || curl -sf http://127.0.0.1:8765/health
```

`workspace/` is unchanged by rollback. For data corruption, extract files from `$BACKUP_ROOT/workspace-full.tgz` selectively (model, rules, feather shards) — do not blindly overwrite a running site without stopping containers first.

## Alternative: Ansible image-only upgrade

If you have inventory and SSH from a control machine (no manual `sed` on the VM):

```bash
export OPENFDD_IMAGE_TAG=2026.06.07-edge
RUN_POST_CHECK=1 ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
```

See also [Updating the stack](../quick-start/updating).
