---
title: Patch cycle (tiny rev)
parent: Operations
nav_order: 3
nav_exclude: true

---

# Patch cycle — tiny VERSION rev + local stack re-pin

**Hosting is the local single-host stack only** ([LOCAL_HOSTING.md](LOCAL_HOSTING.md)).
Railway and any cloud web-app hosting are retired and prohibited. The old 3.3.x
Railway hub train (backup → `railway` re-pin central → mqtt → web → public-URL
stress) is `historical/non-executable`; see git history and
[`patch_trains/`](patch_trains/) for the record.

Qualification entry (tiers + manifest): [`scripts/qualification/README.md`](../../scripts/qualification/README.md) (Codex-owned).
**Machine death / new bench (historical):** [`BENCH_RECOVERY.md`](BENCH_RECOVERY.md).

## Rev bump rule

| When | VERSION |
|------|---------|
| Ships stack images to GHCR | bump the patch in `VERSION` + workspace `Cargo.toml` |
| Pure evidence / guidance after publish | No bump |
| PyPI `open-fdd` | Do **not** bump unless the Python package changed |

Keep the README tip line in sync with `VERSION` and the current PyPI release.
After publish, pin **`sha-<7>`**. Health must read `<semver>+<fullsha-prefix>`.

## Loop (every rev)

```text
hygiene → VERSION bump + one fix → PR merge → GHCR Publish green
  → resolve sha → tip gate → local re-pin → assert → owned qualification → hygiene
```

```bash
SHA=$(./scripts/ghcr_newest_by_created.py openfdd-central | cut -f2)
./scripts/check_ghcr_tip_stack.sh "$SHA"
./scripts/openfdd_local_repin.sh "$SHA"            # edits OPENFDD_IMAGE_TAG in .env, pull, up -d --no-build
./scripts/ops/assert_local_stack_after_repin.sh "$SHA"
```

Qualification runs on an owned disposable central + web + Timescale stack
(Codex-owned under `scripts/qualification/`), never against a public URL.

## Anti-patterns

- Any Railway / cloud web-app re-pin, deploy config or credential
- Local `docker build` of stack images; `down -v`; volume prune
- Citing an older `sha-*` run for a newer tip
- Leaving open PRs / feature branches after merge
