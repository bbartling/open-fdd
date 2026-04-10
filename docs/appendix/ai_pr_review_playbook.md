---
title: AI PR review playbook
parent: Appendix
nav_order: 20
---

# AI PR review playbook

Use this checklist when an AI agent reviews Open-FDD pull requests.

## Priority order

1. Behavior regressions and runtime risks.
2. Auth/security exposure or secret handling mistakes.
3. Data-model/API contract breaks.
4. Missing tests for changed behavior.
5. Documentation drift for operationally meaningful changes.

## Review output contract

- Findings first, ordered by severity.
- Include concrete file references and reproducible rationale.
- Keep summary brief after findings.
- If no findings, state residual risks/testing gaps explicitly.

