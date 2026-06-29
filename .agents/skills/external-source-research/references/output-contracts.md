# Output contracts

## Finding

```yaml
severity: blocker|high|medium|low|info
title: short actionable title
affected_area: files, symbols, service, endpoint, package, or workflow
evidence: exact file paths, commands, source references, or observed behavior
impact: why this matters
recommendation: smallest defensible next action
validation: command, test, reproduction, or review method
confidence: high|medium|low
```

## Subagent result

```yaml
agent: subagent-name
scope: bounded scope assigned
status: complete|partial|blocked
summary: concise result
findings: []
evidence: []
unknowns: []
recommended_next_steps: []
```

## Research fact

```yaml
id: FACT-001
claim: concise factual statement
source: file/symbol/URL/doc/version/date
applicability: where it applies in this codebase
confidence: high|medium|low
notes: optional caveats
```

## Work item

```yaml
id: WORK-001
priority: P0|P1|P2|P3
owner_hint: role or subsystem, not a person unless known
scope: exact files/subsystems/tests
acceptance_criteria: testable completion criteria
validation: commands or review evidence required
```
