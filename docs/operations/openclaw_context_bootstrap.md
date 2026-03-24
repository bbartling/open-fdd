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

1. [OpenClaw integration](../openclaw_integration)
2. [Open-FDD integrity sweep](openfdd_integrity_sweep)
3. [Operator framework](operator_framework)
4. [AI PR review playbook](../appendix/ai_pr_review_playbook)

