# Patch-cycle release process

A **patch cycle** completes when CI is green, local smoke passes, optional ACME read-only validation passes, changes are committed, and the cycle log is written.

## Authorization flags

| Flag | Action |
|------|--------|
| `RCX_ALLOW_MERGE=0` (default) | Do not merge PRs |
| `RCX_ALLOW_PUBLISH=0` | Do not push GHCR images |
| `RCX_ALLOW_DEPLOY=0` | Do not deploy to ACME |

Set to `1` only when the repo owner authorizes.

## Image bump (when authorized)

1. Tests and `gh pr checks` green.
2. Bump patch tag only.
3. `./scripts/docker_build.sh` and publish via existing GHCR workflow.
4. `./scripts/upgrade_edge_full.sh --limit <host>` when deploy authorized.
5. Re-run overnight validator with `OPENFDD_LIVE_ACME=1`.
