---
title: Usage budget and throttling
parent: Operations
nav_order: 9
---

# Usage budget and throttling

Open-FDD automation and OpenClaw-assisted workflows should behave responsibly when model/API budget is tight.

That applies to:

- OpenClaw chat usage
- Codex / OpenAI model budget
- overnight review loops
- daytime smoke runs
- every-20-minute integrity sweeps
- weather/support API calls

## Goal

Do not let automation burn expensive model budget on low-value repetition.

When usage pressure is high, the system should degrade gracefully:

- keep the most operator-relevant checks
- reduce frequency of expensive AI/browser work
- preserve durable findings to GitHub/docs
- stay useful without going silent too early

## Practical throttle ladder

### Level 0 — Normal

Use the full intended workflow:

- 20-minute integrity sweep
- daytime smoke when requested
- full overnight review
- browser parity when it adds real value
- docs/PDF rebuilds on meaningful changes

### Level 1 — Moderate conservation

Use when model budget is healthy but burn rate is rising.

Actions:

- keep the 20-minute sweep concise
- avoid repeating large narrative summaries in chat
- batch docs updates into fewer larger commits
- prefer one focused rerun over repeated full-suite reruns
- avoid unnecessary weather fetches when test-bench mode is already obvious

### Level 2 — High conservation

Use when account/session budget is tight or approaching a hard cap.

Actions:

- keep the 20-minute sweep to auth + graph + one or two model-derived BACnet checks
- suppress low-signal chatter
- avoid broad browser parity passes unless specifically needed for release confidence
- prefer direct backend/API checks before UI replays
- do not rerun full daytime smoke or overnight review repeatedly for the same known failure mode
- write the failure classification once, then work the fix

### Level 3 — Survival mode

Use when usage is critically constrained or a weekly cap is effectively exhausted.

Actions:

- only run high-signal checks
- prefer local/backend checks over browser/UI checks
- skip optional weather/history enrichments
- skip long narrative output
- skip docs/PDF rebuilds unless the change is critical
- notify the human clearly that budget pressure is affecting coverage

## Priority order under throttling

If budget is tight, preserve this order:

1. auth verification
2. backend reachability
3. data-model / SPARQL integrity
4. BACnet readability
5. high-signal product regressions
6. browser parity extras
7. weather/context enrichments
8. long prose summaries

## Applying this to the Open-FDD workflows

### Every-20-minute integrity sweep

Under pressure:

- keep it short
- use model-derived checks only
- do not repeat the same alert every cycle
- if a failure is already known and unchanged, stay quiet unless the state materially worsens or recovers

### Daytime smoke

Under pressure:

- prefer targeted reruns instead of full reruns
- fix the first blocker before repeating the whole suite
- use the short-day BACnet profile ([`openclaw/bench/e2e/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/e2e/README.md))

### Overnight review

Under pressure:

- keep the overnight run focused on evidence gathering and high-signal failures
- avoid chat spam
- distill durable lessons into docs once instead of narrating every small step

## What can be inferred from usage tools

Useful signals include:

- session/model usage status
- visible Codex/OpenAI usage dashboard state
- repeated provider failures or hard-cap symptoms
- evidence that a task is re-spending tokens on the same known issue

The system should use those signals to reduce repeated model-heavy work.

## Important limitation

OpenClaw can adapt its own behavior, but it does not directly control provider billing/quotas.

So the right design is:

- observe usage pressure
- throttle the workflow behavior
- preserve the most valuable engineering checks
- keep the human informed when coverage is reduced by budget pressure
