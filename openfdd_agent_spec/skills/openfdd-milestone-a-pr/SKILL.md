---
name: openfdd-milestone-a-pr
description: >-
  Use when executing Milestone A bounded PRs: inventory, parity tests, cutover,
  twin deletion, CodeRabbit loop, cross-repo pin bumps. Triggers on: Milestone A,
  twin delete, parity proof, PR_PROTOCOL, migration matrix.
---

# Milestone A PR skill

1. Read [`MILESTONE_A.md`](../../MILESTONE_A.md) + [`BUILD_CHECKPOINTS.md`](../../BUILD_CHECKPOINTS.md).
2. Follow [`PR_PROTOCOL.md`](../../PR_PROTOCOL.md) exactly.
3. One architectural purpose per PR; use `milestone-a/<name>` branches.
4. Required pattern:

```text
inventory → characterize → shared impl → parity → cutover
→ delete duplicate → regression → docs → SESSION_LOG
```

5. After Open-FDD PyPI changes: separate playground PR + GHCR refresh.
6. Fill evidence into PR body; update checkpoints when phase status changes.
7. Stop only on exit criteria or documented external blocker.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-architecture`](../openfdd-architecture/SKILL.md) — boundaries a PR must keep
- [`openfdd-stress-closeout`](../openfdd-stress-closeout/SKILL.md) — when a patch needs a stress row
