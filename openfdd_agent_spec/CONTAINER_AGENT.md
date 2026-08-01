# Container agent — GHCR refresh and verify

Test **channel** for Open-FDD stack: **`nightly`** (master publishes retarget
`:nightly` to tip `sha-*`). Treat `nightly` as a pointer only — always verify
and run against the resolved immutable `sha-<7>` digest.

Playground demos: **`develop`** tags for `vibe19` / `vibe20` (same rule:
resolve to digest / `sha-*` when verifying a merge).

Never trust the GHCR web “Latest” alone. Never assume a running container
updated itself.

---

## Open-FDD stack (nightly → immutable)

Product UI after Phase 2 exit: **React** (`compose.react.yml` → host `:3000`).
Streamlit (`openfdd-ui`) is archive-only (`streamlit-legacy` profile).

OT LAN benches need fieldbus too — use recipe **`react-ot`**
(`compose.react.yml` + `compose.react.fieldbus.yml`). Full stress suite:
[`scripts/nightly-ot-bench/`](../scripts/nightly-ot-bench/README.md).

```bash
# 1) Discover tip SHA after merge (or use known short SHA)
SHORT=$(git -C ~/open-fdd rev-parse --short=7 origin/master)

# 2) Pull immutable tags for published stack images
for img in openfdd-central openfdd-fieldbus openfdd-mqtt; do
  docker pull "ghcr.io/bbartling/${img}:sha-${SHORT}"
done
# Archive Streamlit (optional recovery only):
# docker pull "ghcr.io/bbartling/openfdd-ui:sha-${SHORT}"

# 3) Prove nightly currently points at the same digests
for img in openfdd-central openfdd-fieldbus openfdd-mqtt; do
  docker pull "ghcr.io/bbartling/${img}:nightly"
  n=$(docker image inspect "ghcr.io/bbartling/${img}:nightly" --format '{{index .RepoDigests 0}}')
  s=$(docker image inspect "ghcr.io/bbartling/${img}:sha-${SHORT}" --format '{{index .RepoDigests 0}}')
  test "$n" = "$s" || { echo "MISMATCH $img nightly=$n sha=$s"; exit 1; }
done

# 4) Bring stack up pinned to that SHA
#    openfdd-web is often not on GHCR yet — stack_up builds web from frontend/web only
export OPENFDD_IMAGE_TAG="sha-${SHORT}"
cd ~/open-fdd
./scripts/openfdd_stack_pull.sh react-ot
./scripts/openfdd_stack_up.sh react-ot --no-pull
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/ui/generation   # expect generation=react
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
curl -fsS http://127.0.0.1:8081/health               # fieldbus (react-ot)

# 5) Full OT stress (optional — needs OT LAN + bench.env.local)
# ./scripts/nightly-ot-bench/run_all.sh
```

Day-to-day convenience may set `OPENFDD_IMAGE_TAG=nightly`, but Milestone
qualification and post-merge verification must use `sha-*` as above.

Recipes:

| Recipe | Compose | UI |
|--------|---------|-----|
| `react` | `compose.react.yml` | React SPA |
| `react-ot` | react + `compose.react.fieldbus.yml` | React + fieldbus OT |
| `standalone` | `compose.standalone.yml` | Streamlit only with `--profile streamlit-legacy` |

---

## Playground vibe19 / vibe20

```bash
# After develop merge — pull and recreate (do not expect in-place update)
docker pull ghcr.io/bbartling/vibe19:develop
docker pull ghcr.io/bbartling/vibe20:develop
# Prefer recording digests:
docker image inspect ghcr.io/bbartling/vibe20:latest --format '{{index .RepoDigests 0}}'
```

After PyPI API changes: update playground pins → PR → merge → wait for
`vibe19-ghcr` / `vibe20-ghcr` on `develop` → pull → **recreate** containers.

---

## MCP

```bash
SHORT=$(git -C ~/open-fdd rev-parse --short=7 origin/master)
docker pull "ghcr.io/bbartling/openfdd-mcp:sha-${SHORT}" 2>/dev/null \
  || docker pull ghcr.io/bbartling/openfdd-mcp:nightly
```

Separate workflow from the stack. Hub/network flakes: diagnose, one documented
rerun, then fix — do not infinite-rerun.

---

## Safety

- Never commit OT LAN addresses, API keys, or MQTT kit PEMs.
- Live BACnet **writes** need explicit operator approval (`BENCH_ALLOW_WRITES=1`
  on the nightly OT harness). Default gates are read/poll/discover.
