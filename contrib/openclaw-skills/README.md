# OpenClaw skills for Open-FDD

These folders are **[AgentSkills](https://agentskills.io)-compatible** skills for OpenClaw. Each directory contains a `SKILL.md` with YAML frontmatter plus operator instructions.

## Install

Copy (or symlink) the skill folders you want into your OpenClaw **workspace skills** directory so they take precedence for that workspace:

- Default workspace: `~/.openclaw/workspace/skills/`

Example (Unix):

```bash
mkdir -p ~/.openclaw/workspace/skills
cp -R contrib/openclaw-skills/open-fdd-modeling ~/.openclaw/workspace/skills/
cp -R contrib/openclaw-skills/open-fdd-drivers ~/.openclaw/workspace/skills/
cp -R contrib/openclaw-skills/open-fdd-bacnet ~/.openclaw/workspace/skills/
```

Restart or reload the gateway if required by your OpenClaw version.

## Workspace bootstrap (SOUL / MEMORY / AGENTS)

For OpenClaw’s Markdown bootstrap context (same idea as upstream `SOUL.md`, `MEMORY.md`, `AGENTS.md`), copy:

- [`../openclaw-workspace/`](../openclaw-workspace/README.md)

## Related docs

- [`scripts/OPENCLAW_RUNBOOK.md`](../../scripts/OPENCLAW_RUNBOOK.md) — `start-local`, MCP URLs, smoke prompts  
- [`docs/open-fdd-claw-architecture.md`](../../docs/open-fdd-claw-architecture.md) — architecture, Codex auth via gateway  
