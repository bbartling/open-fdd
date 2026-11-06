# Open-FDD agent spec (5.0)

Compact context for AI coding agents (Claude Code, Cursor, Codex) working on Open-FDD 5.0, a Normal Framework (NF)
app. The 4.x spec (Rust central stack) lives at tag `v4.0.11-central`.

| File | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the app is built: UI, hooks, editions, data flow |
| [DATA_CONTRACT.md](DATA_CONTRACT.md) | SI units, result-point tags, how points bind to rule roles |
| [skills/](skills) | Task recipes, each with steps and the tests to run |

Skills: [add-rcx-chart](skills/add-rcx-chart.md), [add-or-tune-fdd-rule](skills/add-or-tune-fdd-rule.md),
[model-a-site-in-nf](skills/model-a-site-in-nf.md), [deploy-to-nf-box](skills/deploy-to-nf-box.md),
[security-checks](skills/security-checks.md), [typescript](skills/typescript.md).

## How agents use it

1. Start with the repo-root `AGENTS.md` (layout, rules, tests, what never to do). Claude Code reads it through
   `CLAUDE.md` or directly; Cursor and Codex read `AGENTS.md`.
2. Open the one skill that matches the task and follow its steps and test list.
3. Pointers in `.claude/skills/<name>/SKILL.md` and `.agents/skills/<name>/SKILL.md` let Claude Code and Cursor
   auto-select a skill; they only point here, so edit the skill files in this folder.

Keep this spec small and true: every rule must hold for the current code. When code changes a rule, change the doc
in the same PR.
