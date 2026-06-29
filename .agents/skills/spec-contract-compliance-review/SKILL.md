---
name: spec-contract-compliance-review
description: Use to compare any codebase against a specification, API contract, protocol, policy, RFC, security baseline, or product requirements document. Builds a traceability matrix and prioritizes compliance gaps.
---
# Spec or Contract Compliance Review

## Trigger

When the user asks for spec compliance, standards compliance, contract conformance, acceptance criteria mapping, protocol review, regulatory/product policy review, or requirement traceability.

## Non-goals

Do not certify compliance. Report evidence and gaps. Do not assume untested paths are compliant.

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

- `spec-tracer` — Break the spec/contract into requirement IDs, MUST/SHOULD/MAY language, and testable assertions.
- `codebase-mapper` — Find implementation paths, APIs, services, state machines, config, and data models related to each requirement group.
- `test-verifier` — Map existing unit/integration/conformance tests to requirements and identify missing coverage.
- `correctness-reviewer` — Review implementation behavior against high-risk requirements and edge cases.
- `security-reliability-reviewer` — Review security, error handling, concurrency, fail-closed behavior, and abuse cases for applicable requirements.

## Workflow

1. Define compliance target: source document, version, scope, explicit exclusions, and what counts as evidence.
2. Create a requirement inventory. Preserve requirement IDs, normative strength, and source location.
3. Group requirements by implementation area to keep subagent scopes small.
4. Map each requirement to code, tests, docs, and runtime behavior. Use `not found` rather than guessing.
5. Prioritize gaps by severity, user impact, interoperability/compliance risk, and testability.

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
# Compliance review

## Scope
- Spec/contract:
- Version/date:
- Included areas:
- Excluded areas:

## Traceability matrix
| Req ID | Requirement summary | Strength | Implementation evidence | Test evidence | Status | Gap |
|---|---|---|---|---|---|---|

## High-risk gaps
| Severity | Req ID | Finding | Evidence | Recommended fix | Validation |
|---|---|---|---|---|---|

## Coverage summary
- Implemented and tested:
- Implemented but not tested:
- Not implemented:
- Ambiguous / needs owner decision:

## Next work items
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
