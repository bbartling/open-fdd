---
name: codebase-research-pass
description: Use for structured research on an unfamiliar or complex codebase before planning, reviewing, or editing. Delegates mapping, ownership, dependency, test, and risk discovery to focused subagents and returns an evidence-led research brief.
---
# Codebase Research Pass

## Trigger

When the user asks to understand a codebase, map architecture, plan work, investigate a subsystem, onboard to a repo, or prepare for implementation/review.

## Non-goals

Do not make code changes. Do not produce implementation plans before mapping the real code paths and validation surfaces.

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

- `codebase-mapper` — Map architecture, entry points, package/module boundaries, data/control flow, ownership signals, and main abstractions.
- `test-verifier` — Identify test commands, fixture strategy, CI gates, coverage signals, and untested high-risk paths.
- `external-researcher` — Verify external APIs, frameworks, protocols, standards, or dependency behavior only when relevant.
- `release-risk-reviewer` — Identify operational, deployment, migration, compatibility, and maintenance risks in the discovered area.

## Workflow

1. Charter the research: objective, codebase root, target subsystem, expected deliverable, and hard constraints.
2. Discover repository shape: languages, packages, entry points, CI, test runners, generated code, docs, deployment surface, and ownership signals.
3. Spawn scoped subagents. Keep at least one subagent read-only and one subagent focused on validation/test evidence.
4. Synthesize a map: key paths, data flows, public APIs, invariants, and dependency boundaries.
5. Produce a research brief with confidence levels and follow-up questions.

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
# Research brief

## Scope and confidence
- Scope inspected:
- Confidence: high | medium | low
- Not inspected:

## System map
| Area | Files / symbols | Responsibility | Notes |
|---|---|---|---|

## Execution paths
| Scenario | Entry point | Key calls | State / IO | Tests |
|---|---|---|---|---|

## Validation surface
- Existing commands:
- Existing tests:
- Missing tests:

## Risks and unknowns
| Severity | Risk | Evidence | Follow-up |
|---|---|---|---|

## Recommended next steps
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
