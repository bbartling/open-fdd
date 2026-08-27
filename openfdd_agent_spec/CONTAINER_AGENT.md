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

Product UI: **React** (`compose.react.yml` → host `:3000`). Central image is
**Rust on debian-slim** (no Python). Analytics and FDD are DataFusion SQL.

OT LAN benches need fieldbus — recipe **`react-ot`**
(`compose.react.yml` + `compose.react.fieldbus.yml`). Full stress suite:
[`scripts/nightly-ot-bench/`](../scripts/nightly-ot-bench/README.md).

**Pi 3 edges (~905 MiB):** run **fieldbus-only** (no central/web soak). Prefer
native `linux/arm64` `openfdd-fieldbus` from GHCR multi-arch (Plan 3 CLOSED on
bosspi `sha-fadf167`); qemu-amd64 is fallback only when arm64 pull is unavailable.

Post-merge soak: **wait for** `Publish Open-FDD stack to GHCR` (+ MCP) **success**
on the tip SHA before pulling `sha-<7>`. Tip git SHA can exist minutes before
GHCR tags. Prefer:

```bash
cd ~/open-fdd
./scripts/nightly-ot-bench/00_pull_ghcr_up.sh
# or full suite:
# WEATHER_SOAK_SECS=120 ./scripts/nightly-ot-bench/run_all.sh
```

Manual pin path (only after GHCR Actions are green for that SHA):

```bash
SHORT=$(git -C ~/open-fdd rev-parse --short=7 origin/master)

for img in openfdd-central openfdd-web openfdd-fieldbus openfdd-mqtt; do
  docker pull "ghcr.io/bbartling/${img}:sha-${SHORT}"
done

export OPENFDD_IMAGE_TAG="sha-${SHORT}"
cd ~/open-fdd
./scripts/openfdd_stack_pull.sh react-ot
./scripts/openfdd_stack_up.sh react-ot --no-pull
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/ui/generation   # expect generation=react
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

Day-to-day convenience may set `OPENFDD_IMAGE_TAG=nightly`, but qualification
and post-merge verification must use `sha-*`.

### Low-RAM hosts (bensbench)

Do **not** `docker build` stack images or run full local Rust compiles for
central/web — OOM risk. Ship code via PR → GH Actions →
`Publish Open-FDD stack to GHCR`, then refresh the host:

```bash
# 1) free disk / drop unused digests before pull
docker image prune -f
docker images 'ghcr.io/bbartling/openfdd-*' --format '{{.Repository}}:{{.Tag}} {{.ID}}' | head

# 2) pull + up (no rebuild)
./scripts/openfdd_stack_pull.sh react   # or react-ot
./scripts/openfdd_stack_up.sh react --no-pull
curl -fsS http://127.0.0.1:8080/api/health
```

Confirm `/api/health` (or UI generation) reflects the new `+sha`, and that Lab
params such as FC1 `confirm_min` match the merged tip.

### Offline WattLab export (not product)

`tools/wattlab_export` is optional PyPI/offline tooling. Product central does
**not** ship Python. To run dumps on a bench, set
`OPENFDD_WATTLAB_PYTHON_EXPORT=1` and mount script + interpreter — never
required for health, FDD, or Overview analytics.
