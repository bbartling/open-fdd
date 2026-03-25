---
title: OpenClaw context bootstrap
parent: Operations
nav_order: 3
---

# OpenClaw context bootstrap

This page defines how to keep context durable and portable for future OpenClaw sessions and new machines.

## Store in Git (durable)

- Operating philosophy and sweep cadence.
- Failure classification standards.
- SPARQL/query patterns that generalize.
- Operator playbooks and runbooks.
- API workflow contracts and tool usage patterns.

## Keep local/private (do not commit)

- API keys, bearer tokens, `.env` secrets.
- Raw auth stores and private local databases.
- Full raw transcript exports with sensitive state.

## Portability principle

Same tools, any building: repo stores reusable process, while site-specific truth lives in the Open-FDD live model.

## Minimal bootstrap read list for fresh clones

**OpenClaw + lab (files in repo — read in order on first session):**

1. `openclaw/HANDOFF_PROTOCOL.md` — mailbox handoff with `issues_log.md` and log files.
2. `openclaw/SKILL.md` — agent behavior, bootstrap modes, MCP, security scope.
3. `openclaw/references/testing_layers.md` — where pytest vs bench vs `bootstrap.sh` live.
4. `openclaw/references/legacy_automated_testing.md` — redirect from deprecated **open-fdd-automated-testing** if anything still points there.

**Product and operations (published docs paths):**

5. [OpenClaw integration](../openclaw_integration)
6. [Open-FDD integrity sweep](openfdd_integrity_sweep)
7. [Operator framework](operator_framework)
8. [AI PR review playbook](../appendix/ai_pr_review_playbook)

**AI data modeling (when the stack includes model/API):** [LLM workflow](../modeling/llm_workflow), [AI-assisted tagging](../modeling/ai_assisted_tagging), plus `GET /data-model/export` and `PUT /data-model/import` as in OpenClaw integration.

