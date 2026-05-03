# OpenClaw workspace bootstrap (Open-FDD)

Copy these Markdown files into your OpenClaw **workspace** root (same directory OpenClaw loads bootstrap context from — typically the workspace folder configured for your agent, often under `~/.openclaw/workspace/`).

OpenClaw recognizes basenames such as **`AGENTS.md`**, **`SOUL.md`**, **`MEMORY.md`**, **`HEARTBEAT.md`**, **`TOOLS.md`** (see upstream OpenClaw bootstrap docs).

## Install (example)

```bash
# Adjust if your OpenClaw workspace path differs
WS=~/.openclaw/workspace
mkdir -p "$WS"
cp contrib/openclaw-workspace/*.md "$WS/"
```

Then install **skills** (separate from these files):

```bash
mkdir -p ~/.openclaw/workspace/skills
cp -R contrib/openclaw-skills/open-fdd-bootstrap ~/.openclaw/workspace/skills/
cp -R contrib/openclaw-skills/open-fdd-clean-metrics ~/.openclaw/workspace/skills/
cp -R contrib/openclaw-skills/open-fdd-modeling ~/.openclaw/workspace/skills/
cp -R contrib/openclaw-skills/open-fdd-drivers ~/.openclaw/workspace/skills/
cp -R contrib/openclaw-skills/open-fdd-bacnet ~/.openclaw/workspace/skills/
```

## Related

- [`../openclaw-skills/README.md`](../openclaw-skills/README.md) — AgentSkills bundles for bridge/MCP
- [`../../scripts/OPENCLAW_RUNBOOK.md`](../../scripts/OPENCLAW_RUNBOOK.md) — ports, health, smoke flows
- [`../../docs/open-fdd-claw-architecture.md`](../../docs/open-fdd-claw-architecture.md) — built-in Codex CLI vs optional OpenClaw gateway, topology, skills/workspace strategy
