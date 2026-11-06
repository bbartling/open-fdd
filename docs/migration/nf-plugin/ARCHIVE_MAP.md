---
title: Removed in 5.0
parent: Architecture
nav_order: 4
---

# What was removed in 5.0, and where it lives

Open-FDD 5.0 is a complete reset ([ADR-014](../../architecture/adr-014-open-fdd-as-nf-plugin.html)). Everything
below is gone from the tree and recoverable from git:

- **Tag `v4.0.11-central`** (branch `release/4.x`) is the last 4.x state. `git checkout v4.0.11-central` has all of it.

| Removed | What it was |
|---|---|
| Rust workspace (`services/central`, `edge`, `mcp`, `crates/*`) | The `openfdd-central` binary: NF ingest into its own Timescale, REST + JWT, static UI; the MCP proxy; shared crates |
| `docker/`, `deploy/caddy/`, `Dockerfile.mcp`, `frontend/`, `config/nf/` | Compose stacks, GHCR images, old Caddy files, React/static UI notes |
| GHCR, stack and release scripts and workflows | Image tag/prune tooling, stack up/pull/health scripts, central smoke tests |
| Qualification, security-harness and gate scripts and tests | Portal/ZAP qualification of the compose stack, architecture and OpenAPI gates |
| The old React and static product UI | Replaced by `nf-app/static` |
| 4.x documentation | Central, GHCR, compose, Rust, Timescale ingest, waves and patch trains, runbooks, vibe19 notes |
| `openfdd_agent_spec/`, `.agents/`, `.claude/skills` | 4.x agent prompts and skills |

Kept: `sql/fdd` (the rule math), the `open_fdd` PyPI package (pandas reference rules), `tools/rdf-check`,
`scripts/nf`, `deploy/nf-caddy`.

The detailed per-item evidence table (the old slice-8 archive map) is in git history of this file, at the commit
before the 5.0 docs reset.
