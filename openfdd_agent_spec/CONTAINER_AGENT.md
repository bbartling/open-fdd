# Container agent — GHCR refresh and verify

Test **channel** for Open-FDD stack: **`nightly`** (master retargets `:nightly`
to tip `sha-*`). Treat `nightly` as a pointer only — always verify and run
against the resolved immutable `sha-<7>` digest.

Playground demos: **`develop`** tags for `vibe19` / `vibe20` (external).

Never trust the GHCR web “Latest” alone. Never assume a running container
updated itself.

---

## Open-FDD stack (nightly → immutable)

Product UI: **React** (`compose.react.yml` → host `:3000`). Central image is
**Rust on debian-slim** (no Python). Analytics and FDD are DataFusion SQL.

OT LAN benches need fieldbus — recipe **`react-ot`**
(`compose.react.yml` + `compose.react.fieldbus.yml`). Full stress suite:
[`scripts/nightly-ot-bench/`](../scripts/nightly-ot-bench/README.md).

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

### Offline WattLab export (not product)

`tools/wattlab_export` is optional PyPI/offline tooling. Product central does
**not** ship Python. To run dumps on a bench, set
`OPENFDD_WATTLAB_PYTHON_EXPORT=1` and mount script + interpreter — never
required for health, FDD, or Overview analytics.
