# Container agent — GHCR refresh and verify

Test **channel** for Open-FDD stack: **`nightly`** (master retargets `:nightly`
to tip `sha-*`). Treat `nightly` as a pointer only — always verify and run
against the resolved immutable `sha-<7>` digest.

Playground demos: **`develop`** tags for `vibe19` / `vibe20` (external).

Never trust the GHCR web “Latest” alone. Never assume a running container
updated itself.

**Unmerged frontend is not in GHCR.** If `frontend/web` is dirty or not on
`master`, `ghcr.io/bbartling/openfdd-web:sha-*` / `:nightly` is the **wrong
demo**. Build a local bundle, bind-mount `dist`, run
`./scripts/openfdd_demo_gate.sh --local-web`, and only then paste a Caddy URL.
Say “local Overview bundle, not GHCR.”

**Published tip ≠ tag name.** Pick newest-by-OCI-`created`:

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
```

Do not `docker pull …:nightly` and tell the user they are on tip. Pin
`OPENFDD_IMAGE_TAG` to that `sha-*`, recreate, then
`./scripts/openfdd_demo_gate.sh --ghcr-web`. If the gate fails, fix serve —
do not hand out `http://192.168.204.55/auth` and blame the user.

---

## Open-FDD stack (nightly → immutable)

Product UI: **React**. 4.0 default recipe is **`portal`** (`compose.portal.yml` +
Timescale → host `:3000`): central + web, no MQTT broker and no fieldbus. Central
image is **Rust on debian-slim** (no Python). Wave-X **3.6.0+**: analytics and FDD
are **Timescale + `sql/fdd/*.sql`**. Storage mandate: **Timescale/PostgreSQL only,
one canonical telemetry write path, no dual record writing**; Parquet, Arrow, Arrow
IPC, Feather and DataFusion are prohibited in product storage, caching, execution
and dependencies ([`DATA_CONTRACT.md` § Storage mandate](DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).
Bring-up: [`docs/operations/TIMESCALE_WAVE_X.md`](../docs/operations/TIMESCALE_WAVE_X.md)
· ADR-010 · ART REBOOT_SAFE under `/tmp/openfdd-softopen/3.6.0/`.

OT wire recipes are `historical/non-executable`. `openfdd_stack_up.sh` refuses
`react-ot`. The archive render does not start containers:

```bash
OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```

Snapshot: `archive/ot-edge/unqualified-cdaa4f15/`. See
[`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../docs/archive/ai-agent/historical-3.5-ot-ops.md).

**Local UI/API are plain HTTP** (`:3000` / `:8080`) behind a firewall — product
Compose does **not** terminate TLS yet. See
[`docs/operations/LOCAL_DEPLOYMENT.md`](../docs/operations/LOCAL_DEPLOYMENT.md).

Post-merge soak: **wait for** `Publish Open-FDD stack to GHCR` (+ MCP) **success**
on the tip SHA before pulling. Tip git SHA can exist minutes before GHCR tags.
Pick the image by OCI `created`, not by the git tip alone and not by the tag
name `nightly`:

```bash
cd ~/open-fdd
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
export OPENFDD_IMAGE_TAG="sha-<that>"
./scripts/openfdd_stack_pull.sh portal
./scripts/openfdd_stack_up.sh portal --no-pull
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

`openfdd_stack_up.sh` refuses `standalone`, `edge`, and `react-ot`. Fieldbus and
MQTT pulls are `historical/non-executable`
([`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../docs/archive/ai-agent/historical-3.5-ot-ops.md)).

### Low-RAM hosts (bensbench)

Do **not** `docker build` stack images or run full local Rust compiles for
central/web — OOM risk. Ship code via PR → GH Actions →
`Publish Open-FDD stack to GHCR`, then refresh the host:

```bash
# 1) free disk / drop unused digests before pull
docker image prune -f
docker images 'ghcr.io/bbartling/openfdd-*' --format '{{.Repository}}:{{.Tag}} {{.ID}}' | head

# 2) pull + up (no rebuild) — local firewall path; Railway lab is central + web
./scripts/openfdd_stack_pull.sh portal
./scripts/openfdd_stack_up.sh portal --no-pull
curl -fsS http://127.0.0.1:8080/api/health
```

Confirm `/api/health` (or UI generation) reflects the new `+sha`, and that Lab
params such as FC1 `confirm_min` match the merged tip.

**Always:** one agent; no parallel Vibe13 cargo/Ansible TX with ZAP; prune zap/MCP
disposables after stress. Wave I wait filler (Vibe13) is OK — not a second Cursor session on the same train.

### Offline WattLab export (not product)

`tools/wattlab_export` is optional PyPI/offline tooling. Product central does
**not** ship Python. To run dumps on a bench, set
`OPENFDD_WATTLAB_PYTHON_EXPORT=1` and mount script + interpreter — never
required for health, FDD, or Overview analytics.

---

## Analytics RAM and local disk budget

Timescale is the historian and the only telemetry store. Analytics / RCx / fault results persist in PostgreSQL or bounded memory. The result cache is the PostgreSQL `analytics_result` table and is not telemetry. CSV buildings load for a query and unload when the job finishes, the SPA leaves the site, or the idle timer fires. Max interactive sessions default to 2. There is no MQTTS ingest buffer on the product path.

**Memory:** prefer lookback-bounded Timescale SQL. DataFusion spill-pool variables are not the tip path ([ADR-010](../docs/architecture/adr-010-timescale-hard-cutover.md)). See [`AFDD_MODES.md`](../docs/operations/AFDD_MODES.md).

Local/edge data budget defaults to 100 GiB oldest-first across `history/` (a known-gap file tree on current images; the budget prunes it and is not a permission to keep it) and legacy `analytics_results/` files, which central no longer writes. Before an on-box full backup or patch, run `scripts/openfdd_disk_preflight.py`. Do not plan 100 GiB live plus another 100 GiB backup on a ~200 GiB disk. Test deploys skip backups unless `OPENFDD_BACKUP_ON_UPDATE=1`. Railway eviction is a separate knob (`OPENFDD_DATA_BUDGET_ENABLED`). Soft-OPEN lab program: **no backups** unless Ben asks — keep historian volumes live across image refresh. Docs: [`ANALYTICS_RESULT_CACHE.md`](../docs/operations/ANALYTICS_RESULT_CACHE.md), [`DATA_RETENTION_BUDGET.md`](../docs/operations/DATA_RETENTION_BUDGET.md).

## Ops patch cycle (portal)

`architecture_epoch: portal-timescale-v1`. Retired Wave L pins and the mqtt re-pin order are `historical/non-executable` in [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../docs/archive/ai-agent/historical-3.5-ot-ops.md).

| Step | Action |
| --- | --- |
| Fix | One PR. Do not bump VERSION for a guidance-only change. |
| Publish | Wait for GHCR Publish green on the merge sha |
| Choose the image | `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web` |
| Tip gate | `./scripts/check_ghcr_tip_stack.sh sha-<7>` |
| Re-pin | Railway CLI backup, then central, then web after `/api/health` is 200 |
| Smoke | `GET /api/health` on the pinned sha |
| Qualification | Owned disposable central + web + Timescale. Not a public Railway ZAP. |

**Auth / MT smoke (Kali O2c — do not regress):** With `OPENFDD_JWT_SECRET` set, unauth
`GET /api/tenants` (and capabilities / health/stack / building/snapshot /
dashboard/summary) must be **401** — never Admin-via-`dev_anonymous`. Public
readiness = `GET /api/health` only. Local regression:
`cargo test -p openfdd-central --test preauth_disclosure`. Live ACL = gate 31;
headers/`security.txt` = gate 34. Skill:
[`skills/openfdd-mt-security/SKILL.md`](skills/openfdd-mt-security/SKILL.md).
**Qualification:** an owned disposable central + web + Timescale stack, with authenticated portal checks and explicit budgets. A public Railway ZAP is not that check. Codex owns `scripts/stress/` and `scripts/qualification/`.

**Volume restore:** disposable empty volume only. Never restore over a live Railway workspace.

Session log: [`SESSION_LOG.md`](SESSION_LOG.md). Machine port: [`AI_CONTEXT_HANDOFF.md`](../docs/operations/recovery/AI_CONTEXT_HANDOFF.md).

