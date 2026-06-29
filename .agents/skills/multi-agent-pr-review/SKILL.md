---
name: multi-agent-pr-review
description: Use for rigorous pull request, branch, patch, or diff review. Runs focused review subagents for correctness, security/reliability, tests, docs/API behavior, and release risk, then synthesizes actionable findings.
---
# Multi-Agent PR Review

## Trigger

When reviewing a PR, branch vs base, patch, diff, merge request, code change, or completed implementation.

## Non-goals

Do not nitpick style unless it hides a real defect. Do not rubber-stamp. Do not make broad edits unless explicitly asked after review.

## Operating principles

- Stay evidence-led. Every non-obvious conclusion must be backed by file paths, symbols, command output, issue/PR links, or source references.
- Keep subagents narrow. Give each subagent one question, a bounded search area, and an explicit output contract.
- Prefer read-only exploration until the parent task explicitly asks for edits.
- Separate facts, inferences, risks, and recommendations.
- Do not rely on repository claims alone. Verify against source code, tests, CI, docs, generated artifacts, runtime behavior, and external specifications when available.
- Treat commands as evidence only when their exact command line, environment assumptions, and result are recorded.
- Preserve user intent. Do not widen scope without stating the proposed scope change.
- Be portable across stacks. Infer language, framework, build system, package manager, test runner, and CI from the repository rather than assuming any one ecosystem.

## Subagent orchestration rules

Use subagents when the task benefits from context isolation, parallel exploration, independent verification, or specialized expertise. Do not spawn subagents for a one-shot formatting task.

When spawning subagents, pass this minimum packet:

1. Objective: one sentence describing the question to answer.
2. Scope: files, folders, PR diff, services, packages, or docs to inspect.
3. Constraints: read-only vs write, commands allowed, network/doc lookup allowed, and timeout.
4. Required evidence: exact files/symbols/commands/sources to cite.
5. Output schema: use the schema requested by the skill.

Parent-agent responsibilities:

- Assign non-overlapping scopes when possible.
- Wait for all requested subagents unless a blocking failure makes remaining work irrelevant.
- Cross-check subagent conclusions against each other.
- Resolve conflicts explicitly. Do not silently choose the more confident subagent.
- Produce one synthesized result with a risk-ranked decision, not a paste of raw subagent notes.

## Recommended subagents

- `codebase-mapper` — Summarize changed files, affected execution paths, public API changes, config/schema changes, and ownership.
- `correctness-reviewer` — Find functional bugs, edge cases, data model errors, backwards compatibility issues, and behavior regressions.
- `security-reliability-reviewer` — Find security flaws, auth/permission risks, secret handling, injection, race/concurrency, resource exhaustion, and fail-open behavior.
- `test-verifier` — Run or inspect appropriate tests, identify missing regression coverage, and verify test commands.
- `external-researcher` — Verify framework/API behavior if the diff relies on external or version-sensitive behavior.
- `release-risk-reviewer` — Assess rollout, migration, observability, compatibility, docs, and operational risk.

## Workflow

1. Establish base and head. If a VCS is available, identify changed files and commits; otherwise review the supplied patch.
2. Classify the change type: feature, fix, refactor, dependency, config, migration, docs, test, release, or mixed.
3. Spawn subagents with non-overlapping review lenses and concrete output schemas.
4. Deduplicate findings, discard speculative issues without evidence, and escalate only actionable risks.
5. Return review findings in severity order with exact reproduction or verification steps.

## Required final output

Return results in this order:

1. **Decision / state** — ready, not ready, inconclusive, or needs follow-up.
2. **Evidence summary** — the smallest set of facts that supports the decision.
3. **Findings** — severity, title, affected area, evidence, impact, and recommendation.
4. **Gaps / unknowns** — what was not verified and why.
5. **Next work items** — ordered, scoped, and testable.

Use severity labels consistently:

- `blocker`: likely correctness, security, data loss, compliance, release, or customer-impact issue.
- `high`: real risk with plausible production impact or major maintainability cost.
- `medium`: important gap, incomplete test, migration risk, or design debt.
- `low`: useful improvement with limited impact.
- `info`: context, observation, or non-actionable note.

## Skill-specific output schema

```markdown
# PR review

## Change summary
- Base/head:
- Files reviewed:
- Commands run:

## Decision
approve | request changes | comment only | inconclusive

## Findings
| Severity | Title | Evidence | Impact | Recommendation | Validation |
|---|---|---|---|---|---|

## Missing coverage

## Follow-up, non-blocking

## Subagent notes
| Agent | Scope | Result |
|---|---|---|
```

## Useful shared references

When this package is copied whole, use these templates as needed:

- `shared/references/evidence-ledger-template.md`
- `shared/references/review-report-template.md`
- `shared/references/research-brief-template.md`
- `shared/references/spec-compliance-matrix-template.md`
- `shared/references/benchmark-report-template.md`
- `shared/references/review-severity-rubric.md`
- `shared/references/safe-research-practices.md`
