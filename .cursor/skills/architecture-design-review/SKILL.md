---
name: architecture-design-review
description: Use to evaluate architecture, design proposals, refactors, module boundaries, dependency direction, data flow, concurrency model, and maintainability tradeoffs across any codebase.
---
# Architecture and Design Review

## Trigger

When the user asks for design review, refactor review, architecture review, modularization, dependency cleanup, long-term maintainability, or tradeoff analysis.

## Non-goals

Do not rewrite the system. Do not optimize for style-only preferences. Anchor design feedback in concrete risk, testability, or operability impact.

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

- `codebase-mapper` — Map current architecture, module boundaries, ownership, data/control flow, dependency direction, and extension points.
- `correctness-reviewer` — Find behavior-preservation risks, invariants, and edge cases that a design change must maintain.
- `security-reliability-reviewer` — Assess isolation boundaries, failure modes, concurrency hazards, resource exhaustion, and safe defaults.
- `test-verifier` — Identify current and required tests to make the design safe to change.

## Workflow

1. Clarify the design question and the decision needed: choose, approve, reject, revise, or sequence work.
2. Map current architecture before evaluating alternatives.
3. Identify invariants, coupling, operational constraints, deployment constraints, and data migration concerns.
4. Evaluate alternatives using impact, reversibility, testability, complexity, and migration cost.
5. Return a decision record or review memo with concrete next steps.

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
# Architecture review

## Decision needed

## Current architecture evidence
| Area | Evidence | Notes |
|---|---|---|

## Invariants and constraints

## Alternatives
| Option | Pros | Cons | Risks | Validation |
|---|---|---|---|---|

## Findings
| Severity | Finding | Evidence | Recommendation |
|---|---|---|---|

## Recommended plan
1. ...
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
