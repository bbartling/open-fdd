---
name: Open-FDD security stress integration audit
overview: Source audit, implementation contract, and adversarial acceptance tests for reusable Python security tooling in qualification runs.
isProject: false
---

# Security regression evidence in qualification runs

## Status and scope — 2026-09-18

Reviewed checkout: `4a5c11e50b921df83f2ca3a59c52d4e99908157f` (3.5.28), plus local changes. This is a source audit, not a deployed penetration-test result. Recheck symbols and route registrations if HEAD changes. Do not revise historical qualification reports or interpret their PASS as retrospective security certification.

This handoff defines work still to implement. `scripts/security/openfdd_security_probe.py`, its suites, and gates 25/25b/26 are **proposed**, not completed. The accompanying change to `write_manifest.py` improves rollups and rejects empty/all-inapplicable qualification; it does not validate HTTP evidence, register the proposed gates, or prove app isolation. The offline manifest tests test reporting logic only.

The current patch-cycle plan says HOLD TIP and Stage C/Kali parked. Implement tooling and offline tests now; preserve that deployment/stress hold. No Railway re-pin, live scan, data mutation, secret retrieval, or OT operation is part of this handoff. Use one agent at a time on bensbench and CI for heavy Rust/container work.

**Claim to produce:** “The named controls passed for this candidate, configuration, fixture set, and run.” A test suite cannot prove absence of all vulnerabilities. Application correctness, availability under load, and security controls need separate verdicts.

## 1. Findings in existing qualification tooling

Paths below are repository-relative; search named functions when lines move.

| Priority | Evidence in checkout | Required correction |
|---|---|---|
| P1 | `31_wave_n_tenant_acl.sh` / `33_wave_o_admin_datamodel_acl.sh` accept 401 as a foreign-object denial; gate 33 only warns when an own-site session-config read fails | Validate identity and successful own-object content first. A broken/expired login cannot demonstrate authorization. Foreign access needs documented 403/404 and deny schema. |
| P1 | Gate 31 does not validate building-list status/schema before absence checks; tokens may fall back from file-user login to admin-minted agents | Invalid JSON, empty/error lists, wrong identity, or missing fixtures must not pass. Report file users and minted agents as separate cases. |
| P1 | `auth_role_matrix.sh` treats absent operator credentials and rejected viewer JWTs as N/A; comments incorrectly say viewer password login does not exist (`auth.rs` supports `OPENFDD_VIEWER_PASSWORD`) | Use configured roles and `/api/auth/me`. Missing credentials are BLOCKED. No hub signing secret is needed for normal role tests. Update stale comments. |
| P1 | `run_railway_hub_stress.sh` records Wave L gates 12–17 as PASS when MT is on despite not running them | Use justified applicability per gate. Do not blanket-exclude A/B isolation. Superseded coverage needs an explicit replacement check ID, not a fabricated PASS. |
| P1 | `run_gate` maps exit 0 to PASS and every nonzero to FAIL; most evidence is just a log | Validate structured results; preserve ERROR/BLOCKED/SKIPPED. Exit/result disagreement or missing result is ERROR. |
| P1 | Gates 31 and 33 share `acl.log`, `acl_verdict.json`, `health.json` when given the same artifact directory | Allocate unique run/gate/phase directories. Include and verify result-file hashes, not only console logs. |
| P1 | Gate 31 submits a confirmed foreign append; gate 33 submits user mutations with fixed names/passwords and weak cleanup | A supposedly denied operation can succeed when the app is broken. Move these to disposable staging/CI fixtures; random generated passwords; verify state after denial and cleanup. |
| P2 | Gate 34 swallows CORS request errors; checks headers largely by presence; login throttle absence is a warning after targeting admin 12 times | Transport failure is ERROR. Validate policy values. Test throttling deterministically with a disposable account/isolated limiter; do not throttle shared admin during stress. |
| P2 | Manifest previously rolled up only ZAP/auth. The first extension also counted MQTT continuity as access-control evidence | Roll up recorded ACL/tenant gates, keep continuity and pause/resume in transport. Adding gate names does not require their execution. |
| P1 | Manifest v1 ignores missing artifact paths when recording, does not recheck hashes at finalization, and accepts arbitrary required-gate lists | Implement a versioned profile/evidence validator. Current v1 is a verdict summary, not an attestation. |
| P2 | `ACCEPT_ZAP_MEDIUM` defaults to 1 in Railway stress | Replace blanket acceptance with rule-specific, target-scoped dispositions with owner, rationale and expiry. Accepted risk remains visible. |
| P2 | `run_all.sh` has no dedicated security verdict phase; neither runner has the specified before/after security contract | Add profile/evidence integration below. A candidate change during stress invalidates a single-candidate result. |

Gate 06 is public ZAP baseline; 07 is role smoke; 20 calls script 31; 21 calls script 32 (MQTTS continuity); 22 calls script 33; 23 calls script 34. Gate IDs and script numbers differ. Passive ZAP alerts and telemetry arrival do not establish tenant isolation.

## 2. Product concerns to reproduce in isolation

These are static observations and hypotheses. Trace router middleware, handler, and storage together; do not declare every context-free handler exploitable without reproducing it. Preserve correct single-tenant behavior while testing MT enabled.

| Priority | Source / observation | Regression required |
|---|---|---|
| P1 | `routes.rs::resolve_tenant_context` catches resolution errors and returns `single_tenant_passthrough`; `tenant.rs` rejects empty non-admin membership but passthrough sets `multi_tenant=false` | A valid operator/viewer/agent with empty claims cannot read either tenant in MT mode. Unknown membership and missing/malformed control plane never broaden access. Exercise real middleware and handler. |
| P1 | `auth_agent_token` checks role Admin but accepts optional/arbitrary `tenant_id`; scoped admin and hub admin have distinct policy elsewhere | A scoped admin cannot mint broader authority; omitted/blank/foreign scope cannot become deployment-wide agent access. Valid hub-admin mint has a positive control and bounded TTL. |
| P1 | Jobs list/get/update/download handlers, dataset/session handlers, and global actions/command surfaces need an ownership trace; several lack caller context | A/B list/detail/write/download matrix, nested child under wrong parent, admin/viewer controls; denied writes leave fixture state unchanged. |
| P1 | `fdd_session_config_get/put` gate building IDs then call shared session-config storage functions | Trace namespace through storage. A's permitted update cannot change B's configuration/cached results. Reuse a building label in distinct tenants if supported; otherwise prove duplicate IDs are rejected explicitly. |
| P2 | `auth.rs::verify_bearer` pins HS256 and validates expiry; audience validation is disabled and no user-revocation lookup is visible here | Preserve signature/algorithm validation. Document issuer/audience trust domain, lifetime, disable/delete/password-change and logout semantics. Test intended behavior; missing `aud`, `iss`, MFA or revocation is not automatically a proven exploit. Raise unmet deployment requirements separately. |

Keep detailed reproductions and sensitive findings private per `SECURITY.md`. Do not attach raw hub data to public issues.

## 3. Harness contract

### Target profiles and budgets

- Require an exact configured origin and explicit profile; do not infer authorization from a hostname containing “production” or a Railway environment name.
- `live_readonly`: bounded approved reads, login and local session handling for known test identities. No token mint, fixture provisioning, append, delete, jobs, broker actions or throttle bursts. Denial probes on write endpoints are still write attempts.
- `isolated_full`: auth-on disposable app, A/B fixtures, isolated workspace, no fieldbus/real broker bridge; explicit `--allow-fixture-writes` for allowlisted fixture mutations. Flags/config are noninteractive authorization; do not add a second interactive confirmation in CI.
- `local_open`: intentionally auth-off local deployment. Auth isolation is untested/inapplicable. Loopback binding requires process/Compose/socket evidence; HTTP reachability alone cannot prove it. Remote exposure or inability to establish the precondition blocks this profile. Never certify public/shared-tenant readiness.
- Default invocation is dry-run: no DNS, network, credential reading or fixture writes. Explicit `--execute` starts traffic; it conflicts with `--dry-run`. Dry-run emits `executed=false`, never a security PASS.
- Defaults: concurrency 1, 1 request/second, 10 s request timeout, 300 s run deadline, 200 total requests, 1 MiB decompressed response cap. Report expected matrix size. Insufficient/exhausted budget is BLOCKED, never truncated coverage. Permit explicit higher bounded budgets for larger isolated matrices. Count login, controls, cleanup and retries; reserve cleanup budget and stop new mutations when unavailable.
- Verify TLS/hostname. HTTP only for configured loopback in isolated/local profiles. No `--insecure`; test CA is explicit. Reject URL credentials, fragments, arbitrary query base URLs and origin mismatches. Disable automatic redirects and environment proxies by default. Never follow off-origin download links or forward bearer tokens/cookies on redirects. Unexpected 3xx is not denial PASS. Separately allowed download origins need their own explicit credential policy.
- No automatic mutation/login retries. Bounded transient retries only for approved reads, counted in budget. Stop new probes on sustained 429/5xx, deadline or repeated transport failures; remaining required checks are BLOCKED. Attempt only previously authorized scoped cleanup.

### Identities, fixtures, expected policy

Config holds environment-variable references, not credentials. Required isolated identities: hub admin; A operator; B operator; A viewer; A scoped agent; multi-membership user; scoped admin if supported. Keep separate clients/token state; never fall back to admin or swap identity classes. Verify subject, role, memberships and active tenant via login/me contracts; JWT decoding alone is not identity verification.

Fixture manifest supplies independently known tenant/building/object IDs and synthetic canaries, including a non-existent object control. Seed through supported APIs or isolated builders with ownership ledger and verified cleanup. Own-data controls must match expected IDs/content. Confirm B's object exists using B before requesting it as A, and repeat B→A. No arbitrary IDs harvested from live tenant data.

Each route record specifies method, actual template, request schema, selectors, public/auth policy, expected role/tenant scope, statuses, response schema/canaries, side effects, fixture needs and source/test references. Derive it from registrations and request types; do not invent DELETE URLs or POST bodies. Compare registrations against this checked-in inventory in CI. Every in-scope method has a test or justified exclusion; zero checks, unknown suites or silently missing routes cannot pass. A required route returning 404 is not proof it is inapplicable.

Direct protected objects require documented 403 (or reviewed 404 concealment) with no foreign content and the deny envelope (`ok:false` where contracted). Collections require schema-correct own data and absence of foreign canaries. A 200 empty list is not object denial. A 401 with a nominally valid tenant token invalidates the authorization case; check `/me` to distinguish policy failure from expired credentials. 429, 5xx, timeout, parse failure, redirect or SPA HTML are never authorization PASS.

### Mandatory coverage

1. **Preauth:** lean public health/auth status/login; anonymous 401 for tenants, capabilities, health/stack, building/snapshot, dashboard/summary and registered protected APIs. Detect protected data in error bodies too.
2. **Authentication:** valid A/B/admin/viewer login; generic invalid-login errors; me identity; tenant selection/multi-membership; safe return paths in browser tests. No spraying/enumeration. Browser logout must clear credentials/private caches and return to auth; server revocation follows explicit policy. Record UI gaps.
3. **JWT:** valid control plus missing/malformed/tampered signature, `alg:none`, disallowed algorithm, unsupported role, missing required claim and expiry boundary. Expiry enforcement needs a correctly signed expired token and valid sibling through the actual app. Generate keys only in isolation; never fetch the Railway signing key. Use controllable clock or account for leeway. Test `nbf`/`iat`, issuer/audience against adopted policy; decoding expiry is not enforcement. No key cracking or remote key callbacks.
4. **A/B and roles:** equipment/results/series/session config, mappings/TTL, CSV sessions/plans/fusion preview, dataset preview/delete, all analytics, tenant select, jobs/runs/findings/dispositions/export/download, admin APIs, agent token scope/TTL, edge metadata and command ACK ownership. Audit actions, export/meta, host/stats, data-management/summary, fdd-schema/tables, ingest/stats, agent/tools: explicit admin/public/tenant policy, not automatic approval of current behavior.
5. **Selectors/state:** vary path/query/body selectors individually, omit/blank, conflict, nested parent-child references; valid-schema controls prevent parsing errors masquerading as authorization. Interleave A/B reads at identical URLs for cache isolation. Isolated viewer/foreign mutations verify unchanged state, authorized disposable control and cleanup. Mixed-owner batches only where supported. Bound all variants.
6. **Web/deployment:** CSP directives/sources with legitimate Fonts/Plotly needs, nosniff, referrer/framing policy, HTTPS HSTS at proxy, security.txt status/text/plain/contact/expiry. CORS permitted-policy controls plus disallowed origins on preflight and actual authenticated responses; distinguish public resources/credentialed reads. CSRF where ambient credentials are used. Real-browser/Playwright tests establish browser behavior; Python response checks cannot.
7. **Abuse:** malformed requests and bounded pagination/size limits; deterministic throttle/recovery in isolation with disposable identities and appropriate edge/IP scope. Test failure then recovery using test clock/isolated config; never sacrifice live availability for throttle tests.
8. **MQTT where applicable:** isolated broker with synthetic certs/identities and fixture topics. Own pub/sub succeeds; foreign pub/sub and cross-tenant wildcards denied; anonymous/invalid/revoked certificates follow configured policy. Verify broker reason codes/logs and non-delivery with healthy own-topic control; client publish success alone is insufficient. No live commands, OT writes or real broker ACL changes. Continuity gate 21 is not this suite.

### Verdicts, evidence and privacy

Use versioned JSON plus Markdown/JUnit rendered from the same model. Statuses: PASS, FAIL, ERROR, BLOCKED, SKIPPED, NOT_APPLICABLE; WARN is separate diagnostic, not a required-check substitute. Exit 0 only for complete passing execution (or explicitly identified successful dry-run plan); 1 for demonstrated contract failure; 2 for incomplete/error/blocked execution. Qualification rejects dry-run regardless of exit code.

- PASS: required applicable checks/controls ran and matched policy with verified evidence. FAIL: observed violation, reproducible sanitized facts. ERROR: tool/transport/parse/evidence fault prevents evaluation. BLOCKED: missing identity, fixture, budget, environment, prerequisite or policy decision. SKIPPED: deliberately not run. N/A: feature demonstrably absent or profile exclusion with reason/evidence; missing credentials are never N/A.
- Planned/executed/passed/failed/error/blocked/skipped/N/A counts and IDs reconcile; coverage denominator is declared inventory, not passing requests. Required exclusions are reviewed.
- Metadata: unique run ID, profile, origin (private alias in shareable summary), times, candidate source/image digest and revisions before/after, harness commit plus dirty content digest, policy/fixture/config digests without secrets, request/budget/cleanup counts. Candidate drift invalidates single-candidate qualification.
- Evidence: method/template, identity alias, policy/check ID, expected/observed status/schema, canary comparisons, control IDs, duration and sanitized assertions. Findings use `wave_kali_finding_template.md`. No full bodies/raw headers/tokens/token hashes/passwords/cookies/private URLs/PEMs/customer data/signed download URLs. Allowlist fields before serialization; sanitize exceptions/stdout/stderr. Directories 0700, files 0600; reports private/untracked.
- Hash final redacted artifacts only. Paths relative to run root; reject traversal/off-root paths/symlinks/duplicate paths or check IDs/reused run IDs. Write atomically; verify hashes/schema at finalization. Missing, modified, stale, wrong profile/candidate/phase or dry-run evidence is ERROR. Hashes prove matching bytes, not correct assertions.

## 4. Stress and CI integration

Create a versioned profile registry with required check IDs, role/route coverage, features, phases and permitted exclusions. Add a reviewed manifest schema revision/migration where needed; keep legacy reports readable without upgrading their assurance claim.

1. Both runners record profile before traffic. `live_readonly`, `isolated_full`, `local_open` have different scopes; live smoke PASS never means full isolated coverage. Show `security_scope` and coverage counts.
2. Railway: required `25_security_python_harness` before stress; required `25b_security_post_stress` after. Postcheck validates credentials anew, then preauth protection, A/B own+foreign reads and viewer checks allowed by profile. Finalize even after preceding failures. Postcheck cannot erase precheck failure.
3. Required `26_security_mqtt_acl` when broker security is in profile. Missing usable broker evidence is BLOCKED, never continuity-as-PASS. Do not splice unrelated isolated results into live proof; linked CI evidence needs exact candidate/config binding and scope shown separately.
4. Local: same library/schema, local-open limitations explicit or full isolated auth-on fixtures. Keep security probes out of high-frequency OT loops. Attach coverage references to CSV/FDD/job phases instead of repeating the matrix on every request.
5. Repair gates 07/20/22/23 and skipped-as-PASS Wave L paths; until then label limited legacy smoke. Gate 31/33 mutations and gate 34 throttle must not run implicitly in read-only profiles.
6. Validate exit code AND structured result AND digests AND expected nonzero check set. Required missing/FAIL/ERROR/BLOCKED/SKIPPED prevents full qualification within scope. N/A requires feature/profile proof; all-N/A security is no PASS. Unknown required IDs/schema fail closed. New route without disposition fails inventory coverage.
7. ZAP dispositions remain visible. Never skip controls to retain old qualification badges. Suite subsets report partial coverage; caller-controlled suite/gate removal must not produce full-profile PASS.

## 5. Evaluate the evaluator

Three layers, separate results:

**A. Offline harness tests:** strict origin/TLS/redirect/config/profile handling, secrets, budgets/deadlines/body caps, cleanup/idempotency, status/schema checks, inventory/matrix and report validation. No hub credentials.

**B. Deliberately broken local HTTP fixtures:** each defect must trigger its intended check, not an unrelated outage. Include always-401; own/foreign 200 empty JSON; SPA HTML 200; wrong login identity; ignored tenant filter with foreign canary; foreign content inside 403; cached A data returned to B; viewer mutation allowed; disabled-user login transport error; ignored JWT signature/expiry; reflected credentialed CORS. Also off-origin redirect to a counting sink (zero requests/credentials received), oversized response, timeout, exhausted budget, cleanup failure. Require zero false PASS for specified faults and PASS for healthy controls. Map each fault to detector ID; skipping the detector fails evaluation.

**C. Actual app regressions:** drive Rust router/middleware/storage with temporary workspaces/test keys in existing tests or CI disposable containers. Run the same fixture matrix through the real HTTP app where possible. Reproduce product concerns, add failing tests before focused fixes, demonstrate passing afterward; retain pre-fix result or isolated mutation test. Fake servers/Python decoding do not test Rust verification. Browser checks use real UI. No heavy Rust compilation on bensbench.

**Orchestrator sabotage tests** with offline subprocess stubs, never real stress defaults: child exit 0 with missing/invalid/FAIL report; child nonzero with PASS report; zero checks; duplicate IDs; dropped required suite; stale/wrong candidate/profile; dry-run artifact; overwritten/hash-mismatched artifact; required missing gate; all N/A; omitted postcheck; failed cleanup; expired risk acceptance. Assert nonzero qualification exit and `fully_qualified=false`; include a valid complete run. Inject runner/HTTP dependencies so tests cannot pull containers/contact Railway accidentally.

## 6. Cursor completion checklist

- [ ] Route inventory and policy/fixture manifests; unresolved policy explicit.
- [ ] Python library/CLI, example nonsecret config, schema, README, safe examples.
- [ ] Actual results for three test layers; CI-only/live-unverified items named.
- [ ] Broken fixtures demonstrate detectors fail when controls are broken.
- [ ] Both runners, pre/post phases and repaired legacy verdicts tested offline.
- [ ] Evidence validator/sabotage tests block all listed false-PASS cases.
- [ ] Cleanup, privacy, budgets and expiring risk dispositions verified.
- [ ] Security guide, qualification README and session log describe shipped/pending scope accurately.
- [ ] Completion: commands/exit codes, revisions, coverage, changed files, private finding IDs, limitations. No “security certified” or “100% secure” claim.

## Source methodology

Original project test design informed by PortSwigger's identity/permission distinction ([access control](https://portswigger.net/web-security/access-control)), authentication failure modes ([authentication learning path](https://portswigger.net/web-security/learning-paths/authentication-vulnerabilities)), and signature/claim validation ([JWT](https://portswigger.net/web-security/jwt)). These learning references do not demonstrate Open-FDD has passed any test.
