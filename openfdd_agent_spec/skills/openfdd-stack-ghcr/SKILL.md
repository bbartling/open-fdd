---
name: openfdd-stack-ghcr
description: >-
  Use when pulling, rebuilding, or verifying Open-FDD GHCR stack images.
  Test channel is nightly. Triggers on: nightly, openfdd-ui, openfdd-central,
  GHCR, openfdd_stack_up, OPENFDD_IMAGE_TAG.
---

# Stack GHCR (nightly)

Full protocol: [`CONTAINER_AGENT.md`](../../CONTAINER_AGENT.md).

```bash
export OPENFDD_IMAGE_TAG=nightly
./scripts/openfdd_stack_pull.sh standalone
./scripts/openfdd_stack_up.sh standalone
```

Verify immutable `sha-<commit>` matches `:nightly` before trusting a refresh.
Workflow: `ghcr-openfdd-stack.yml` (retargets nightly on master).
MCP: separate `rust-ghcr-mcp.yml`.
