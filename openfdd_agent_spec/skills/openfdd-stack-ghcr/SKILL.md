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

Product central image is Rust/debian only (no Python).

Workflow: `ghcr-openfdd-stack.yml` (retargets nightly on master).
MCP: separate `rust-ghcr-mcp.yml`.
