# Workspace cron — reference

Configured in `openfdd.toml` `[cron]`.

Implementation: `packages/openfdd-agent-shell/src/openfdd_agent_shell/cron/`.

`codex_turn` payload example:

```json
{"wake_mode": "mini", "message": "optional extra operator goal"}
```

`wake_mode` `critique` triages `workspace/memory/architecture/working-divergence.md` and promotes stable patterns into skills or `MEMORY.md`.

Full wake loop:

```json
{"service": "wake", "payload": {"dry_run": false, "mini_invocations": 2}}
```

Inspired by OpenClaw scheduled tasks: https://docs.openclaw.ai/automation/cron-jobs.md
