# Container agent — GHCR refresh and verify

Test channel for Open-FDD stack: **`nightly`** (master publishes retarget
`:nightly` to tip `sha-*`).

Playground demos: **`develop`** tags for `vibe19` / `vibe20`.

Never trust the GHCR web “Latest” alone. Never assume a running container
updated itself.

---

## Open-FDD stack (nightly)

```bash
export OPENFDD_IMAGE_TAG=nightly   # or leave default if scripts already use nightly
cd /home/ben/open-fdd
./scripts/openfdd_stack_pull.sh standalone   # or csv / central
./scripts/openfdd_stack_up.sh standalone
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

Immutable verify after a merge:

```bash
SHORT=<7-char-sha>
docker pull ghcr.io/bbartling/openfdd-ui:sha-$SHORT
docker pull ghcr.io/bbartling/openfdd-central:sha-$SHORT
docker buildx imagetools inspect ghcr.io/bbartling/openfdd-ui:nightly
# Confirm nightly digest == sha-$SHORT digest before recreating local containers
```

Inspect labels / installed package when debugging UI:

```bash
docker image inspect ghcr.io/bbartling/openfdd-ui:nightly
docker run --rm ghcr.io/bbartling/openfdd-ui:nightly \
  python -c "import open_fdd; print(open_fdd.__version__)"
```

---

## Playground vibe19 / vibe20

Adjust ports to local docs if different:

```bash
docker pull ghcr.io/bbartling/vibe19:develop
docker pull ghcr.io/bbartling/vibe20:develop
# Recreate named containers rather than expecting in-place update
```

After PyPI API changes: update playground pins → PR → merge → wait for
`vibe19-ghcr` / `vibe20-ghcr` on `develop` → pull → recreate.

---

## MCP

```bash
docker pull ghcr.io/bbartling/openfdd-mcp:nightly
```

Separate workflow from the stack. Hub/network flakes: diagnose, one documented
rerun, then fix — do not infinite-rerun.

---

## Safety

- Never `docker compose down -v` or `docker volume prune` against a live site workspace
- Never expose stack on the public internet
- Record tested image digests in Milestone logs / [`COMPLETION_REPORT.md`](COMPLETION_REPORT.md)
