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

```bash
# 1) Discover tip SHA after merge (or use known short SHA)
SHORT=$(git -C ~/open-fdd rev-parse --short=7 origin/master)

# 2) Pull immutable tags for every standalone image
for img in openfdd-central openfdd-ui openfdd-fieldbus openfdd-mqtt; do
  docker pull "ghcr.io/bbartling/${img}:sha-${SHORT}"
done

# 3) Prove nightly currently points at the same digests
for img in openfdd-central openfdd-ui openfdd-fieldbus openfdd-mqtt; do
  n=$(docker buildx imagetools inspect "ghcr.io/bbartling/${img}:nightly" --format '{{println .Manifest.Digest}}')
  s=$(docker buildx imagetools inspect "ghcr.io/bbartling/${img}:sha-${SHORT}" --format '{{println .Manifest.Digest}}')
  test "$n" = "$s" || { echo "MISMATCH $img nightly=$n sha=$s"; exit 1; }
done

# 4) Bring stack up pinned to that SHA (scripts honor OPENFDD_IMAGE_TAG)
export OPENFDD_IMAGE_TAG="sha-${SHORT}"
cd ~/open-fdd
./scripts/openfdd_stack_pull.sh standalone
./scripts/openfdd_stack_up.sh standalone
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/

# 5) Optional UI package assert inside the immutable image
docker run --rm "ghcr.io/bbartling/openfdd-ui:sha-${SHORT}" \
  python -c "import open_fdd; print(open_fdd.__version__)"
```

Day-to-day convenience may set `OPENFDD_IMAGE_TAG=nightly`, but Milestone
qualification and post-merge verification must use `sha-*` as above.

---

## Playground vibe19 / vibe20

```bash
# After develop merge — pull and recreate (do not expect in-place update)
docker pull ghcr.io/bbartling/vibe19:develop
docker pull ghcr.io/bbartling/vibe20:develop
# Prefer recording digests:
docker buildx imagetools inspect ghcr.io/bbartling/vibe19:develop --format '{{.Manifest.Digest}}'
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

- Never `docker compose down -v` or `docker volume prune` against a live site workspace
- Never expose stack on the public internet
- Record tested image digests in Milestone logs / [`COMPLETION_REPORT.md`](COMPLETION_REPORT.md)
