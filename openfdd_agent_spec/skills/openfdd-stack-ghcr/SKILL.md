---
name: openfdd-stack-ghcr
description: >-
  Use when pulling, rebuilding, or verifying Open-FDD GHCR stack images.
  Test channel is nightly. Triggers on: nightly, openfdd-central, openfdd-web,
  GHCR, openfdd_stack_up, OPENFDD_IMAGE_TAG.
---

# Stack GHCR (nightly channel → immutable verify)

Full protocol: [`CONTAINER_AGENT.md`](../../CONTAINER_AGENT.md).

`nightly` is the channel selector. Qualification pulls `sha-<commit>` for
central/web/fieldbus/mqtt, asserts digests match `:nightly`, then starts the
stack with `OPENFDD_IMAGE_TAG=sha-<commit>`.

**Newest means OCI `created`, not the word nightly.** Run
`./scripts/ghcr_newest_by_created.py openfdd-central` before claiming tip.

**Unmerged `frontend/web` → local web only.** `openfdd_stack_up.sh` refuses
GHCR web when the tree drifted (override `OPENFDD_ALLOW_STALE_GHCR_WEB=1`).
Never paste a Caddy login until `./scripts/openfdd_demo_gate.sh` exits 0.

Product central image is Rust/debian only (no Python).

Workflow: `ghcr-openfdd-stack.yml` (retargets nightly on master).
MCP: separate `rust-ghcr-mcp.yml`.
