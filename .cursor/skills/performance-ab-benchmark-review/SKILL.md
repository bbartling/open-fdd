---
name: performance-ab-benchmark-review
description: Use to design, run, or review performance work with reproducible A/B baselines. Delegates benchmark inventory, profiling, correctness guardrails, and result interpretation to subagents.
---
# Performance A/B Benchmark Review

## Trigger

When the user asks about optimization, benchmarking, latency, throughput, memory, profiling, regression baselines, A/B comparison, or performance PR review.

## Non-goals

Do not optimize without a baseline. Do not accept benchmark wins without correctness and variance checks. Avoid microbenchmark-driven architecture unless tied to real workload impact.

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

- `performance-analyst` — Inventory benchmark harnesses, define metrics, run safe benchmarks where allowed, and compare before/after results.
- `codebase-mapper` — Map hot paths, allocation/copy boundaries, IO boundaries, concurrency model, and data structures relevant to the performance question.
- `correctness-reviewer` — Check that optimizations preserve behavior and edge cases.
- `test-verifier` — Identify correctness tests that must pass before and after performance runs.
- `release-risk-reviewer` — Assess operational risks: load shape mismatch, resource limits, deployment variability, and observability gaps.

## Workflow

1. Define the A/B question: baseline commit/state, candidate commit/state, workload, metrics, acceptable variance, and expected risk.
2. Find existing benchmarks and production-like workload proxies before creating new ones.
3. Run correctness checks first when commands are available and safe.
4. Run benchmark matrix with warmup, repeated samples, environment capture, and raw output retention when possible.
5. Interpret results with variance, confidence, and caveats. Recommend only changes supported by measured evidence.

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
# Performance A/B review

## Benchmark question
- Baseline:
- Candidate:
- Workloads:
- Metrics:

## Environment
| Item | Value |
|---|---|

## Commands
```text
# exact commands here
```

## Results
| Workload | Baseline | Candidate | Delta | Variance / confidence | Notes |
|---|---:|---:|---:|---|---|

## Correctness guardrails

## Interpretation

## Follow-up benchmarks
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
