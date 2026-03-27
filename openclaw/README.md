# OpenClaw lab (external bench first)

OpenClaw’s default Open-FDD posture is **external system testing**, not clone-first repo work.

Use OpenClaw as a commissioning-minded tester for a running Open-FDD bench/deployment:
- web app regression testing
- frontend/API parity checks
- BRICK/RDF model validation
- BACnet add-to-model and live read verification
- overnight scrape/FDD/hot-reload review
- bug confirmation and issue filing

Repo-local source edits are optional and only when explicitly requested by the human.

## System under test

Open-FDD is usually treated as an externally running bench or deployment. OpenClaw should test the live frontend, backend API, SPARQL/data-model behavior, BACnet gateway behavior, and overnight logs directly. Repo-local source inspection is supporting context, not the default source of truth.

OpenClaw may run on a different machine than Open-FDD. For split setup details see [`docs/openclaw_integration.md`](../docs/openclaw_integration.md#1e-openclaw-on-a-different-machine-than-open-fdd-split-setup).

## Current bench reality (keep this straight)

- Bench/frontend/backend/BACnet reachability can be healthy while auth context is still wrong.
- Missing or invalid `OFDD_API_KEY` should be treated as **launcher/env/runtime-context drift** unless proven otherwise.
- If Open-FDD is running on another machine, load the active `.env` into the shell or point `OPENCLAW_STACK_ENV` at it before calling auth-sensitive APIs.
- **Do not delete or bury issue `#92`**; keep it as likely real product parity tracking once auth is healthy.
- Do not frame auth-context drift itself as a confirmed product bug without clean repro under known-good auth.

## Testing layers

1. Frontend / web app
   - Selenium workflow validation
   - UI state, error handling, console failures
   - Data Model Testing UI parity
2. Backend / API
   - auth preflight
   - config and data-model endpoints
   - SPARQL query correctness
   - graph integrity checks
3. BACnet integration
   - add-to-model flows
   - address/reference integrity
   - live property reads via gateway
4. Overnight stability
   - long-run scrape review
   - FDD pass/fail review
   - hot-reload verification
   - issue triage
5. Future field mode
   - live HVAC sanity checks
   - operator-style monitoring

## Failure classification

- Auth / launcher / env drift
- Bench limitation
- Frontend/API parity bug
- Graph hygiene / model drift bug
- BACnet integration bug
- Likely real Open-FDD product defect

File GitHub issues for confirmed product defects by default. Track harness/env failures in `openclaw/issues_log.md` unless Ben explicitly asks to file harness issues too.

## Security phases

Track security work as deliberate hardening:
- auth and token handling
- Caddy/reverse-proxy boundaries
- secrets handling
- attack-surface reduction
- phased hardening roadmap items

Do not mix security hardening work casually into unrelated defect triage.

## Near-term vs future role

- Near-term default: test-bench validation and defect confirmation.
- Future live HVAC mode: operator-style checks using time/season/weather/BRICK/live BACnet telemetry.
- In both modes, keep strong web-app bug-hunting skepticism and parity checks.

## Layout (bench-focused)

| Path | Purpose |
|------|---------|
| [`bench/e2e/`](bench/e2e/) | Frontend regression, Selenium, long-run suites. |
| [`bench/sparql/`](bench/sparql/) | SPARQL parity and graph checks. |
| [`bench/fake_bacnet_devices/`](bench/fake_bacnet_devices/) | BACnet fixture devices and validation runs. |
| [`bench/rules_reference/`](bench/rules_reference/) | Reference rules for testing/cookbooks (not auto-live). |
| [`references/`](references/) | Stable protocol/checklist references for agents. |
| [`reports/`](reports/) | Templates and summarized outputs (avoid duplicated policy docs). |
| [`issues_log.md`](issues_log.md) | Ongoing classification trail and evidence index. |

## Standing constraints

- Do not assume clone-first or repo-first workflow.
- Do not assume OpenClaw’s main job is coding changes.
- Start from runtime evidence: UI behavior, API responses, SPARQL, BACnet reads, logs.
- Use repo docs/reference only as support unless local edits are explicitly requested.

## Quick commands (when running from this repo)

```bash
./scripts/bootstrap.sh --verify
./scripts/bootstrap.sh --test
./scripts/bootstrap.sh --mode collector
./scripts/bootstrap.sh --mode model
./scripts/bootstrap.sh --mode engine
```
