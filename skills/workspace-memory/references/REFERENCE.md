# Workspace memory — reference

Configured in `openfdd.toml` `[memory]`.

Implementation: `packages/openfdd-agent-shell/src/openfdd_agent_shell/memory/store.py`.

`memory/architecture/working-divergence.md` is seeded on first shell run and included in the truncated memory bootstrap. It is not a second task queue.

Inspired by OpenClaw `MEMORY.md` + daily notes: https://docs.openclaw.ai/concepts/memory.md
