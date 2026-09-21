---
name: Wave U independent acceptance audit
overview: Repair reproduced false qualifications, finish standalone and field-only security readiness without a Nessus license, and qualify the actual candidate before closing Wave U milestones.
todos:
  - id: ua-reconcile
    content: Reconcile current PRs and active plans with UA-01 through UA-10; reopen unsupported closure claims in BUG_REPORT and MILESTONES.
    status: pending
  - id: ua-evaluators
    content: Add permanent negative and healthy controls for the 14 reproduced cases; repair real evaluators, wrappers, identity checks and required gate contracts.
    status: pending
  - id: ua-standalone
    content: Qualify the actual standalone images and merged Compose recipe from a peer with verified TLS and no plaintext web bypass.
    status: pending
  - id: ua-field-mqtt
    content: Qualify field-only runtime boundaries and product-generated certificates, ACLs, permissions, delivery observers and command lifecycle.
    status: pending
  - id: ua-zap
    content: Consolidate authenticated ZAP runners; prove candidate/auth/route/job coverage and private artifact hygiene on a disposable stack.
    status: pending
  - id: ua-images-host
    content: Remediate image findings and implement host/runtime/exposure readiness checks for both OT deployment profiles; no license required.
    status: pending
  - id: ua-nessus-import
    content: Fix per-host credential/completeness validation and test the Nessus importer offline; keep only the actual licensed assessment BLOCKED.
    status: pending
  - id: ua-product-remainders
    content: Complete or explicitly track remaining MT, S5 modeling/ECM, S3 wheel publish and SQL twin obligations without relabeling partial delivery as completion.
    status: pending
  - id: ua-final-qualification
    content: Run affected candidate gates then final enhanced Railway MEGA with validated evidence and both gate 36 checks required; update milestones, bugs and ops pins.
    status: pending
  - id: ua-portable-handoff
    content: Prove the documented workflow in a clean developer environment with synthetic fixtures and no author-specific credential or path dependencies.
    status: pending
isProject: false
---

# Cursor execution handoff — Wave U independent audit, 2026-09-20

## Authority and immediate action

The developer requests completion of the security requirements, including readiness for a future customer Nessus assessment on **standalone OT** and **field-only OT** deployments. A missing Nessus license blocks the actual licensed assessment only. It does not cancel local hardening, Python tests, image scans, TLS/port checks, host checks or importer tests.

Read this entire file, root `MILESTONES.md`, `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, `services/fieldbus/AGENTS.md`, `docs/operations/WAVE_U_MASTER.md`, `docs/operations/NESSUS_PASS_READINESS.md`, and the original `security_railway_ot_nessus_assurance.plan.md`. This is an acceptance correction **under Wave U**, not another competing master. Preserve original requirements in the assurance plan. The old Wave T sequencing in that plan is historical; Wave U owns execution.

Reconcile the in-flight plan at `~/.cursor/plans/wave_u_fq_closeout_d8895d5d.plan.md` and `.cursor/plans/wave_u_patch_softopen_closeout.plan.md`. Re-read current files before each edit; another Cursor session may have advanced them. Do not reset, stash or overwrite unrelated work. One executing agent on bensbench; no duplicate stress jobs or local product image builds. Use GHCR candidates or CI for heavy integration.

Keep this detailed audit and raw reproductions local/private until findings are resolved and publication reviewed. Public Pages and root milestones should describe supported controls, secure deployment, synthetic examples and aggregate status. Follow `SECURITY.md`; do not publish credentials, private scanner output or unresolved exploit instructions. The audit itself does not authorize live OT writes or scanning provider address space.

## Audit snapshot and executed evidence

Inspected source HEAD: `dc808c8acb315ca9feada97faa21b65ba7773d0f`, PR #961 head at review. GitHub status can change; refresh before proceeding.

| PR / evidence | Observed result |
| --- | --- |
| #959, Wave U 3.5.34 | Merged; merge SHA `f44b45f6f58d7bc21085a56aac06cec23f78598f`. Added real E01–E08 regressions, identity improvements, AppSec jobs and security assets. |
| #960 | Merged; supplies the fieldbus API key for optional BACnet/MQTT CI after fail-closed startup. |
| #961, 3.5.35 | Open at review, head `dc808c8`. Adds RCx presets ACL, gate 26 verdict serialization, ops password aliases and tenant-aware edge CN. Rust/FDD required checks failed; the FDD log shows rustfmt in `provision.rs`. Do not mistake green AppSec for all required CI passing. |
| Existing Python suites | Independently rerun: **55 security tests PASS; 16 qualification tests PASS**. These results cover their implemented assertions. |
| Additional negative cases | **14 incomplete/broken cases accepted** by current evaluators. Actual evaluator functions called with synthetic inputs; scanner/broker execution mocked. No live scan, secrets, Rust build or deployment used. |
| Existing MEGA `20260920T194610Z` | Correctly recorded FAIL, `fully_qualified=false`. Preserve that historical result. |

Private audit files are at `/home/ben/Documents/Codex/2026-09-16/cursor/outputs/wave-u-audit-20260920/`: `reproduce.py`, `negative-cases.json`, `security-tests.log`, `qualification-tests.log`. JSON records source hashes. Run the reproducer with the repo path as its first argument; it exits **1 when false qualification remains**. This helper is a review aid, not a portable runtime dependency. Convert its relevant cases into permanent repo tests with independent healthy controls, then retire the dependency on the Documents path.

No evidence establishes intent to bypass testing. There is evidence of weak evaluators, mismatched scope and unsupported closure. Fix those concrete defects.

## Findings and required corrections

### UA-01 — P1: required tests and candidate evidence do not govern FQ

**Evidence:** `scripts/nightly-ot-bench/run_railway_hub_stress.sh:123` declares required gates through 35, omitting both `36_model_ecm_qualification` and `36_mv_sql_oracle_twin`, although both execute later. `scripts/qualification/write_manifest.py:151` finalizes from that list. A synthetic run with all declared gates PASS and both gate 36 checks FAIL still produces `fully_qualified=true`.

The same finalizer accepts a Railway profile with no candidate SHA, digests or existing evidence artifacts. The actual failed MEGA manifest declares source `3.5.34+f44b45f6f58d`, image tag `sha-c1b1aa5`, and empty digests/start/end revisions. This is inconsistent provenance, not proof of which images ran. `run_security_gate` also trusts a structured PASS without reconciling a nonzero process exit. N/A currently needs only a reason string, not proof of the replacement coverage.

**Fix and acceptance:**

- Declare profile-required gates in one versioned machine-readable contract. Both gate 36 tests are mandatory for the promised Wave U product closeout. Missing, disabled, BLOCKED, FAIL and malformed evidence must prevent that closeout. An optional diagnostic may fail without invalidating unrelated scope, but cannot fulfill a required milestone.
- Parse and validate each gate's actual evidence schema and process outcome. Recompute totals. Reject duplicate IDs, missing artifacts, wrong suite/profile/candidate, stale files, altered hashes, truncated runs and PASS/nonzero contradictions.
- Record full source SHA, actual per-component digest/platform, scanner and harness versions, configuration/fixture hashes, and start/end runtime identities. Pin health version, image tag and OCI revision to one resolved candidate; reject inconsistent or changed deployment state. Distinguish unit profile manifests from deployment qualification so healthy unit tests remain valid.
- N/A requires a specific capability/profile rule and replacement gate evidence where applicable. Missing credentials/dependencies are BLOCKED. Test the exact required gate set, including MT replacements, rather than checking only the number of gates.
- Add regression cases for both gate 36 failures, missing provenance/artifacts, changed digest mid-run, stale PASS after process failure, malformed JSON and unexplained N/A. Do not mark UA-01 verified from serializer tests alone.

### UA-02 — P1: the HTTPS overlay does not close plaintext deployment paths

**Evidence:** rendering the documented merge of `docker/compose.standalone.yml`, `docker/compose.react.yml`, and `docker/compose.standalone.https.yml` with synthetic env preserves **web `0.0.0.0:3000 → 8080`** and MQTT `*:8883`. Central is loopback with the documented setting. The HTTPS overlay never removes the web publication. Its exposure manifest omits web 3000 and declares MQTT loopback despite the rendered publication.

`scripts/security/peer_probe_https.py:210` runs a Python stub behind Caddy, not the candidate application. Its HTTPS client disables certificate and hostname verification at line 249. The cited `reports/security/standalone_https_probe.json` currently contains `mode=selftest`, replacing the stronger historical peer-soak claim. A stub redirect test is useful component coverage but does not qualify a standalone app.

**Fix and acceptance:**

- Make the supported secure recipe enforce its ports in the **resolved Compose config**, including merged-list behavior. Remove direct web/central LAN access or explicitly bind the intended local-only administration ports. Decide whether local MQTT needs LAN clients; enforce and document the chosen interface rather than silently widening the manifest.
- Pass the configured public hostname into Caddy; verify offline customer CA/SAN, validity, trust distribution and renewal. Do not claim ACME env support unless implemented. No `-k`, `verify=False` or unverified SSL context in qualifying positive tests; invalid/untrusted/expired/wrong-host certificates must fail. Test authenticated POST paths as well as GET pages.
- On an isolated supported Linux host, pull the actual central/web/mqtt/fieldbus candidate images, use synthetic device endpoints, and test from a second peer. Compare host sockets, container bindings and observed IPv4/IPv6 exposure with the profile manifest. Verify local firewall behavior with Docker published ports and host networking.
- Test HTTPS login/read/logout flow, forbidden plaintext login, direct proxy bypass, HTTP redirect destination, headers, expected MQTT reachability, fieldbus management denial and startup/restart behavior. Prove the whole app functions without Railway/cloud credentials.
- Keep immutable per-run artifact directories; selftest results cannot overwrite runtime evidence. Reopen `standalone-https-bootstrap` until candidate and peer evidence meet this scope.

### UA-03 — P1: MQTT tests can pass without delivery proof and use different ACLs

**Evidence:** `26_security_mqtt_acl.sh` invokes the observer without `--require-live`. `mqtt_tenant_acl_observer.py:430` reports overall PASS with Docker absent/live SKIPPED, with require-live plus skip-live, and even a live BLOCKED result under its default mode. All three were reproduced.

The foreign-topic subscriber has no positive delivery control on **that topic and connection**; failure to start/subscribe can look like successful denial. Only A own and A→B publish are checked live. The observer uses upstream `eclipse-mosquitto:2` with generated Python fixture ACLs rather than the product MQTT image/entrypoint and Rust provisioner. The fixture grants edge write to its entire `/#` subtree, including commands, while `TopicBuilder::edge_acl_patterns` is narrower. Fixture CNs include tenant/building/edge; current product edge CN uses tenant/edge. Thus the fixture did not exercise the actual mismatch fixed in #961.

**Fix and acceptance:**

- Separate static fixture lint from runtime ACL qualification. A deployment ACL gate requires successful broker startup, both identities, both healthy observers and runtime tests; missing tools or skipped work is BLOCKED. Invalid combinations of CLI flags fail closed. Suite `mqtt_acl` must validate per-check evidence rather than copy the observer's overall label twice.
- Produce disposable credentials/ACLs with the **real provisioning path**, load the actual candidate broker config, and record digest/config hash, authenticated CN, role/topic permissions and loaded ACL path. Compare the fixture contract with real generated output; do not repair a fixture to agree with itself.
- Verify A own/B own, A→B/B→A, same-tenant different building/edge, command read/write direction, `+`/`#` subscribe boundaries, retained messages, no/wrong/expired client certificate and allowed central command delivery plus ack. A positive observer must receive a fresh allowed canary before and after each negative observation window on the same connection/topic. Broker outages, unsubscribed observers, connection errors and stale messages cannot count as denials.
- Test a deliberately permissive broker, stopped foreign observer, wrong identity grammar, altered loaded ACL and denied central command path: each must be detected. Full command execution testing uses a simulated actuator only. Native BACnet writes are outside automatic execution.
- Retained/expired/replayed commands, restart behavior, spool limits, reconnect and tenant binding remain required under the original assurance plan. Continuity alone does not prove ACL correctness.

### UA-04 — P1: authenticated ZAP closure exceeds the evidence

**Evidence:** the new `scripts/qualification/zap/run_af_disposable.py:562` accepts scanner rc=1 with a nonempty site, `site:[{}]`, undispositioned Medium and a stale previous-target report. These four cases were reproduced. It does not prove `/api/auth/me`, expected identity or protected route coverage. Active mode is optional and there is no enforced disposable-target safety boundary.

The older `scripts/qualification/run_isolated_zap_af.sh` remains wired into `.github/workflows/wave-c-isolated.yml`, writes `admin.jwt`, accepts fallback/warning reports, and uploads its whole artifact directory. The reviewed local scan directory no longer contains `admin.jwt`; that does not remove the future script/CI exposure path. Do not claim a confirmed live credential leak from this observation.

The CLOSED row cites `sha-4d3a6b0`, not the Wave U candidate. Its verdict is `PASS_WITH_WARNINGS`; logs show spider root 404, with OpenAPI and passive scan jobs. There is no evidence in this report of completed authenticated active scanning. The legacy CI resolves a PR's **base** image and can fall back to an older fixed tag; this is reference-image testing, not candidate qualification.

**Fix and acceptance:**

- Consolidate entry points onto one evaluator/runner. No legacy fallback can satisfy authenticated acceptance. Scanner errors fail; warnings require named review plus fulfilled coverage. Enforce alert dispositions by plugin/rule, scope, owner, rationale and expiry; fixable High/Critical cannot be waived with an env flag.
- Resolve candidate and scanner digests. Use a fresh output directory with timestamps and run IDs; reject reports from another target/run. Bound subprocess duration and clean up all containers and secrets on success, failure, cancellation and timeout.
- Prove authorization header injection through ZAP traffic with `/api/auth/me` and expected role/subject/membership, plus successful seeded protected endpoints. Record URL/method counts and AF job results; public crawling and nonempty sites alone are insufficient. Test wrong/missing/expired token and all-401/404 responses as negative controls.
- Authenticated active scans run on a disposable candidate with no route to physical OT and a validated target allowlist. Seed legitimate request bodies and A/B/viewer/admin identities. Record which write/business-logic areas Python and browser tests cover separately from scanner rules. Never ActiveScan the live OT-linked hub merely because execute is enabled.
- Remove `admin.jwt` persistence, argv token fallback and world-writable artifact setup. Store ephemeral credentials in restricted temporary storage/environment; sanitize request/response logs, query values, cookies, JWTs and archives before upload. Review already-created CI archives privately, without printing their secrets.
- Add subprocess/wrapper tests and one genuine isolated candidate run. Reopen `zap-af-authenticated` and its `kali-zap-af` alias until that evidence exists.

### UA-05 — P1: image scan completion was treated as hardening completion

**Evidence:** `reports/trivy-wave-u/sha-f44b45f/SUMMARY.md` says the scan script failed, then closes `image-digest-trivy`. The JSON reports contain High/Critical counts central **67**, fieldbus **67**, MCP **56**, web **37**, MQTT **0**; all 37 web entries have FixedVersion values. These counts are per-image findings, not unique exploitable vulnerabilities. No evidence supports dismissing all OS findings as noise.

`trivy_ghcr_digests.sh` scans tags, not explicitly resolved digest references; reports happen to include RepoDigests. It also does not cover the added Caddy image. The predeclared readiness policy requires zero unresolved Critical/High, with reviewed time-bound Medium dispositions.

**Fix and acceptance:** split scan acquisition from remediation and acceptance. Reopen readiness/remediation; keep historical scans intact. Upgrade/rebuild the web runtime base and dependencies, assess other bases/package necessity and supported upgrade paths, then scan the new image digests. An unavailable fixed package remains a tracked unresolved finding unless a specific evidence-backed false-positive determination applies. Do not silently relax the policy or call a vulnerability secure because it is upstream.

Scan every shipped profile component, including TLS front end, with tool/DB timestamp, platform, SBOM and digest. Treat scanner/database failure separately from vulnerability findings. Tests must fail for a missing image, stale/unavailable DB, missing report, wrong digest or unresolved severity. Require image acceptance for the applicable milestone, not just a script file in CI. A readiness milestone cannot be VERIFIED while unresolved required findings remain; document constraints and continue other work.

### UA-06 — P1: Nessus importer misidentifies credentialed and complete scans

**Evidence:** `scripts/security/nessus/import_nessus_report.py` labels the mere presence of plugin 19506 anywhere as credentialed Linux evidence. Synthetic `Credentialed checks : no` passes `require_credentialed=True`; one informational host plus a second unassessed host passes; an empty ReportHost passes default evaluation. All three reproduced. Missing host lists are tested, but incomplete hosts are not.

**Fix and acceptance:** require supported report structure, expected target aliases, per-host successful credentialed Linux package/local-check evidence, scan completion/start/end, scanner/feed version/freshness, selected policy/ports, candidate mapping and private report hash. Parse plugin output rather than the ID alone, and preserve per-host failures. Reject stale, wrong-target, discovery-only, cancelled/truncated, malformed and incomplete reports, including OT early-stop with zero findings. Use hardened bounded XML parsing. Replace blanket `--allow-medium` acceptance with validated dispositions. Synthetic fixtures may validate the importer but cannot become a real assessment PASS.

**No license is needed to finish this work.** Keep the actual licensed assessment separately BLOCKED until a real isolated host scan is available. Do not manufacture `.nessus` evidence.

### UA-07 — P1: tenant identity preflight checks the wrong response field

**Evidence:** `_login_me` at `scripts/security/openfdd_security/suites/__init__.py:481` looks at `tenant_id`, `tenant`, or `tenants`, then skips enforcement when none appears. Actual `/api/auth/me` serializes `tenant_ids` (`services/central/src/routes.rs:1004`). Correct subject/role with foreign `tenant_ids`, and missing expected membership, both produce PASS in independent synthetic cases.

**Fix and acceptance:** validate the real response schema and expected tenant set, with explicit rules for hub admin versus tenant admin. Missing, wrong, extra or malformed membership must fail the relevant fixture control. Do not use administrative tokens as tenant controls. Remove failed tokens from reusable context. Verify actual seeded own-object identity/content before each foreign denial; check denial envelopes for foreign data. Test both directions and same-ID collisions.

The route inventory currently declares 139 routes: 18 IMPLEMENTED, 92 PLANNED, 29 BLOCKED_POLICY. This is an inventory of status, not full route coverage. Finish the required tenant surface matrix with Rust integration, HTTP and browser evidence: lists, FDD results/series/run, all scoped analytics/POSTs, mapping/Turtle/JSON, jobs/status/exports/downloads, SQL/RDF queries, budgets, admin, edge kits and agent tools. Record explicitly unimplemented routes and applicability; “one more route then continue later” does not complete the original breadth requirement.

### UA-08 — P1: file permissions and field runtime still need real deployment tests

**Evidence:** MQTT key protection is tested by source-string checks. The entrypoint's chmod/chown failures are ignored, while Compose mounts certs read-only. The Rust provisioner writes keys with ordinary `fs::write` and uses a kit path based only on site/edge. A source change to mode 640 does not prove secure installed permissions or cross-tenant non-collision. Central and fieldbus runtime Dockerfiles lack USER; fieldbus uses host networking. These are configuration concerns requiring real effective-runtime evidence, not a claimed Nessus finding by themselves.

**Fix and acceptance:**

- Create private keys atomically with restrictive modes and checked ownership, including CA/client/server keys and backup/extraction paths. Test permissive umask, pre-existing insecure files, read-only mounts, wrong UID/GID and failed repair. Fail closed or provision correctly before container start; do not ignore permission errors. Runtime broker must still start and perform allowed/denied traffic.
- Exercise real provisioning for two tenants with identical building/edge IDs and validate separate paths, identity namespace, ACL contents, rotation/revocation and ZIP permissions. Do not break existing kits without an explicit migration/compatibility path. Verify CA/central private keys are excluded from edge downloads.
- Define a **field-only** exposure manifest and supported standalone/field deployment recipes. Verify no local central/web/broker is required for the field-only cloud path. Field management defaults loopback; any remote administration requires a TLS-protected management path or documented protected tunnel, not just an API key over LAN HTTP.
- Evaluate non-root runtime, minimal capabilities, no-new-privileges, read-only rootfs with explicit writable volumes, resource/PID/log/spool bounds and required OT/serial access. Add only the capabilities actually needed by tested drivers. Document justified exceptions rather than making arbitrary hardening break BACnet.
- Verify actual host OS/kernel/packages, SSH policy, Docker API/socket exposure, firewall rules, backups and permission ownership using repeatable read-only checks on an isolated representative host. Do not install SSH inside every container to simulate credentialed host scanning.

### UA-09 — P1: readiness was cancelled and contradictory statuses hide remaining work

The active external FQ plan explicitly said “skip all Nessus work — no readiness closeout”; the patch closeout greyed readiness because of the license. Meanwhile BUG_REPORT and NESSUS_PASS_READINESS labeled readiness/HTTPS/ZAP/MQTT CLOSED. Restore readiness as required work, reconcile canonical rows and link each remaining requirement to an owner, evidence and milestone.

Keep old smoke/scan acquisitions as historical facts. Mark insufficient acceptance as REOPENED/PARTIAL without changing old run files or rewriting old PASS rows as new-suite proof. Scope-specific blockers should not stop unrelated development. An unavailable physical bench can block its measurement, but not code, fixtures, CI or an isolated simulator run. Only explicitly deferred external/commercial requirements stay later; no silent lost scope through superseding plans.

### UA-10 — P2: current PR follow-ups and inherited product obligations need closure evidence

#961 fixes identified product/configuration problems; do not revert correct ACL checks to clear a failing harness. Its diff contains no new permanent regression tests for RCx presets and the provisioning change. Add tests that fail on the pre-fix behavior and pass on the candidate, including admin/scoped admin/operator A/B/viewer/anonymous and product-generated MQTT kits.

S5 DM-04/05 completion does not complete DM-06..10, graph/JSON fidelity, SPARQL query correctness/performance, quantities/units/provenance or ECM adapters. Reconcile DM-06 explicitly rather than losing it between residual lists. S3 math is distinct from a published, clean-installed wheel. Keep SQL/PyPI twins and model/ECM tests mandatory. Use the existing Wave S child plans and data-model review handoff; do not invent a parallel architecture. Verify UI task cancellation/timeout and final FDD results separately from stale-action reclamation.

## Deployment qualification matrix — mandatory readiness work now

| Profile | Actual candidate test | Expected boundary | Evidence that remains separate |
| --- | --- | --- | --- |
| Standalone OT, whole app on one Linux box | central/web/mqtt/fieldbus + supported TLS front end, local storage, synthetic OT peers, no Railway dependency | HTTPS entry; no plaintext web/API management bypass; MQTT limited to needed clients; field HTTP local; OT UDP only within declared peers | Peer network/TLS assessment, host checks, runtime hardening, image scans, full app regression |
| Field-only OT → cloud MQTTS | Actual field image/kit with simulated OT and a disposable cloud broker/consumer | Field management local; outbound verified mTLS; no cloud-exposed BACnet/Modbus; documented command return channel | Product broker/ACL/CN proof, reconnect/spool/command tests, field host checks and peer exposure |
| Railway application hub | Candidate web/central/mqtt (+ MCP when used), with bounded authorized app requests | Web HTTPS and intended mTLS broker ingress; central/MCP private; no fieldbus runtime | App/auth/tenant regressions and image evidence; provider host assessment is not under app control |

For license-free readiness use version-pinned/reported Python checks, Trivy, a suitable TLS tool such as testssl.sh or SSLyze, approved bounded Nmap TCP/UDP checks from a lab peer, and a host audit such as Lynis plus explicit SSH/Docker/permission checks. Select tools by control coverage; adding more scanners is not a substitute for checking their evaluators. Prepare an isolated host before scanning; no whole production OT subnet discovery. A simulator is valid simulator coverage, not a physical-controller certification.

For later Nessus, define external and credentialed host assessments separately. Tenable can stop after recognizing OT services when OT scanning is disabled. A Linux box hosting BACnet can therefore need explicit completeness review; zero findings after early-stop is not a clean host assessment. Safe Checks/low rate reduce risk but do not guarantee controller safety. Do not enable invasive OT scanning without an isolated target or authorized site window.

## Required execution order and stress closeout

1. **Reconcile:** snapshot current branch/head/PRs/checks and active plans. Log UA rows before fixing. Keep #959/#960 historical outcomes and #961's evolving status distinct. Do not re-run an obsolete audit finding blindly after source changes.
2. **Evaluate evaluators first:** add permanent negative and healthy controls for every acceptance hole above. Exercise real shell wrappers and CI entry points, not copied predicates. Require a negative-case test to fail if the relevant guard is removed. Document the red-before/green-after result; do not invert tests to match broken behavior or change expected data to hide failures.
3. **Implement bounded fixes:** restore strict identity/membership, required gates/evidence, secure merged deployment, real MQTT qualification, ZAP, importer and image/host hardening. Product fixes require permanent Rust/browser tests at the actual boundary. Use CI for heavy builds.
4. **Finish isolated candidate qualification:** pin images/digests, run the profile matrix and full authenticated ZAP against synthetic disposable resources. Restore/restart tests operate only on disposable volumes. Fix findings and re-run affected checks after each relevant change. A failed scan or unresolved required vulnerability cannot be represented as an accepted readiness milestone.
5. **Finish product residuals:** execute the existing S5/S3/S4 plans with model/ECM and exact installed-wheel/API comparisons; update Pages for secure deployment, modeling and engineering contracts. Re-measure graph traversal and units/provenance rather than using textual TTL matching as query proof.
6. **Final Railway enhanced MEGA:** after CI/publish and the authorized ops backup/re-pin, use `scripts/nightly-ot-bench/run_railway_hub_stress.sh` with security execute and the correct fixture profile, exact MCP pin and MQTT ACL runtime evidence. No blanket Medium acceptance. Gates 25/25b/26, both 36 checks, expected edge/ingest, capacity and pause/resume must meet the repaired contract. Run pre/post identity and isolation checks and finalize reports on error/cancel. Monitor auth availability, ingestion, spool growth, FDD latency and terminal actions. This is bounded workload validation, not a live active penetration scan.
7. **Close only measured scope:** reconcile the generated manifest independently with run IDs, candidate/config hashes, required gate inventory, actual evidence and process results. Record any failed attempt first, fix, publish/re-pin if needed, then repeat the full final qualification when the candidate changes. Do not count an isolated stub, reference image or historical tip as this candidate's evidence.
8. **Portable handoff and milestone release:** clean checkout + documented Python dependencies + synthetic setup can run evaluator tests and approved isolated gates without Ben's paths or secrets. Use one canonical runbook and thin agent pointers. Update BUG_REPORT, MILESTONES, SESSION_LOG and relevant agent/skill pins at the end. No readiness/OPS PINNED claim solely because a PR merged.

For every stress/retest row record: requirement/UA ID, profile, source/harness SHA, image/platform digests, config/fixture revision, CI/run/artifact IDs with hashes, expected/observed result, tool/DB versions, before/after status, remediation commit, and any bounded disposition owner/expiry. Keep private details out of public reporting.

## Milestone policy

Root `MILESTONES.md` is a compact release index; BUG_REPORT holds operational history and the Wave U master owns sequencing. Track implementation, verification and release separately. Pending PRs and scanning complete are progress, not acceptance. GitHub milestones may mirror this file: group bounded PRs under one outcome, use an aggregate readiness issue with no sensitive details, and close the milestone only when its exit evidence is verified. Do not publish this private audit as an issue body. Remote milestone creation is a separate publication step; this audit creates only the local index.

## Official references for acceptance semantics

- [ZAP Automation Framework exit status](https://www.zaproxy.org/docs/desktop/addons/automation-framework/job-exitstatus/): errors and warnings have distinct outcomes; a report file alone does not negate job failure.
- [ZAP authentication](https://www.zaproxy.org/docs/desktop/addons/automation-framework/authentication/): configure and verify the context/session actually used by scan jobs.
- [Tenable scan discovery](https://docs.tenable.com/nessus/Content/DiscoverySettings.htm): OT early-stop, port coverage and credentialed local enumeration matter when interpreting results.
- [Tenable troubleshooting plugins](https://docs.tenable.com/whitepapers/useful-plugins/Content/UsefulPlugins/TroubleshootingPlugins.htm): credentialed evidence depends on plugin output, not merely plugin 19506 being present.

Do not promise that automation outperforms every expert Burp review, or that a future Nessus policy will find nothing. Deliver reproducible, evaluated checks and explicit remaining limitations. The acceptance target is zero unresolved required findings and complete measured scope, not a persuasive PASS label.
