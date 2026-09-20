---
name: Railway, standalone and OT security assurance
overview: Repair evaluated security-tool weaknesses, qualify three deployment profiles, implement authenticated web and MQTT testing, add Nessus readiness, and make the security workflow portable for new maintainers.
todos:
  - id: reconcile
    content: Reconcile this audit with current HEAD and Wave T; establish deployment/control coverage and private evidence handling.
    status: pending
  - id: evaluator
    content: Reproduce E01–E08; fix false PASS verdicts and weak identity/object controls; enforce them in CI.
    status: pending
  - id: web
    content: Expand Python and browser coverage; qualify authenticated ZAP with verified scan coverage on isolated candidates.
    status: pending
  - id: local
    content: Ship a secure standalone TLS/bootstrap profile and enforce fieldbus management boundaries and container hardening.
    status: pending
  - id: mqtt
    content: Implement tenant-aware broker/command ACL qualification and certificate lifecycle tests using real generated configuration.
    status: pending
  - id: nessus
    content: Deliver repeatable licensed Nessus assessment/import workflow for isolated standalone and fieldbus hosts, plus image scanning.
    status: pending
  - id: handoff
    content: Consolidate durable security context and prove a fresh developer environment can execute the documented workflow.
    status: pending
  - id: qualify
    content: Integrate evaluated gates into appropriate stress profiles and qualify the exact candidate in the authorized release window.
    status: pending
isProject: false
---

# Cursor implementation prompt — security assurance across three deployments

## 1. Mission, evidence and coordination

The developer owns Open-FDD and requests practical improvements to security tools, deployment security and developer handoff. Implement this plan in bounded changes. Use Python regression tools, real application tests, browser tests, ZAP, dependency/image scanning and a repeatable Tenable Nessus workflow. Automated regression should surpass repetitive manual request replay on explicitly measured controls. Do not claim universal superiority to an expert penetration tester, complete ASVS compliance, or a Nessus pass without corresponding evidence.

This is a **local remediation handoff**. Do not publish unresolved findings, raw scanner artifacts or this audit appendix in public issues/Pages. Follow `SECURITY.md` for private findings. Public documentation should explain secure setup, supported controls, synthetic examples and fixed behavior. Security must rely on enforced controls; hiding source code or removing useful API documentation is not a substitute.

Read `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, `services/fieldbus/AGENTS.md`, the multi-tenant security and stress-closeout skills, `.cursor/plans/wave_t_soft-open_closeout.plan.md`, `.cursor/agents/openfdd-security-python-harness.md`, `.cursor/plans/security_stress_integration_audit.md`, `docs/operations/TESTBED_TAKEOVER.md`, local/VM/Railway deployment docs, and actual source before editing. Some old agent instructions still describe the harness as unimplemented; source and current active-plan status must be reconciled explicitly.

Audit performed 2026-09-20. Initial HEAD was `23caf61d338e5d62c4f81cbe319ad28efa376779`; it advanced during Cursor work to `b530f1c6fc47c5a58ba8bac364e2c63329400987`. Recheck current files before applying findings. Reproducer output records hashes of the specific harness files tested. This audit did not pull/merge, change product code, run containers, access deployment credentials, scan Railway, scan OT or execute Nessus.

Executed evidence:

- `python3 -B -m unittest discover -s tests/security -v`: **38 passed** after granting localhost socket access; the initial sandbox-blocked run is not a product failure.
- `python3 -B -m unittest discover -s tests/qualification -v`: **11 passed**.
- Eight additional synthetic cases against actual harness functions/predicates reproduced false PASS results. Reproducer intentionally exits 1 while defects exist. It uses no sockets or application credentials:

  ```bash
  python3 -B /home/ben/Documents/Codex/2026-09-16/cursor/outputs/security-harness-audit-20260920.py /home/ben/Desktop/open-fdd
  ```

  JSON evidence: `/home/ben/Documents/Codex/2026-09-16/cursor/outputs/security-harness-audit-20260920.json`. Existing-test logs are adjacent `security-review-20260920-tests.txt` and `security-review-20260920-qualification.txt`. Convert these cases into permanent repo-relative tests; those author-machine paths are audit references, not a runtime dependency for future maintainers.
- Current inventory reports **138 route records: 16 IMPLEMENTED, 93 PLANNED, 29 BLOCKED_POLICY**. These are inventory dispositions, not a measured percentage of application security. Many request/response schemas remain TODO. The inventory's source hint is older than this audit.
- `nessuscli`, `nessusd` and `nmap` were not found through this shell's PATH. That does not inventory the separate Kali machine or establish license availability.

Adopt relevant work into Wave T `T_sec` and explicit additional children for standalone/OT/Nessus if needed. The current master permits full Railway MEGA at T3 only; mid-tips use smoke. Keep one agent/PR at a time on bensbench, avoid heavy local Rust/container builds, use CI-built immutable images on an appropriate isolated test host, and preserve other work. Historical qualified pins do not qualify a newer candidate. The present request authorizes evaluation and a handoff; implementation agents must follow the applicable existing release authorization for later deployment/active scans.

## 2. Define and qualify all three deployment profiles

| Deployment | Intended exposed services | Required security boundary and test evidence |
|---|---|---|
| Railway web/API hub | HTTPS web origin. Where on-prem edges connect directly, a specifically provisioned MQTTS broker endpoint/TCP proxy is also reachable; a private tunnel is an alternative deployment design. | Central and optional MCP remain private. No fieldbus container, BACnet or Modbus listener in cloud. Authenticated application tests cover the actual web→proxy→central chain. Broker ingress requires certificate authentication and topic authorization. Test external visibility and private-service exposure separately. |
| On-prem fieldbus → Railway | Hosted BACnet/IP only to approved OT peers; management HTTP loopback or explicitly secured management interface. Outbound MQTTS to the approved broker endpoint plus documented operational egress. | No public fieldbus HTTP/BACnet/Modbus exposure. Host firewall, management auth, client certificate isolation, spool protection, and broker ACLs. An edge-initiated MQTT connection also carries subscribed commands: it is not a data diode or a guarantee that cloud-originated instructions cannot reach OT. |
| Standalone local full installation | One authenticated HTTPS UI/API entry point for approved clients; local broker/BACnet only where required. | Same application authorization expectations as cloud, local certificate/trust bootstrap, private direct API/management ports, host and container hardening. Provide a real supported full-stack recipe including the web service; the file named `compose.standalone.yml` currently contains central/mqtt/fieldbus, not the complete UI recipe. |

Create machine-readable exposure manifests: profile, service, interface, TCP/UDP port, authentication, transport protection, approved client/source networks, allowed outbound destinations, image digest, and expected denied paths. Use deployment aliases and environment references, not maintainer hostnames or private inventories. Account for IPv4 and IPv6, Docker bridge and host networking, and the actual Railway broker proxy port rather than assuming public port 8883.

Do not tell operators to keep the broker entirely private while also expecting direct internet-connected edges to reach it. Document the chosen connection route. Never add fieldbus to Railway to solve connectivity.

## 3. Findings that must be reproduced, fixed or explicitly dispositioned

Priority is implementation order. Harness false positives are verified below; deployment concerns are source findings unless an isolated integration test establishes reachability/impact.

| ID | Priority / observed evidence | Required change and verification |
|---|---|---|
| E01 | P1, reproduced: `SecurityReport.reconcile` in `scripts/security/openfdd_security/evidence.py` can set full qualification for an all-SKIPPED executed report. | Reject skipped/missing required checks and zero meaningful executed evidence. Recompute verdict from trusted profile requirements and check results. |
| E02 | P1, reproduced: `validate_report_for_qualification` accepts claimed positive counts/qualification with an empty `checks` list. | Validate schema, result IDs, statuses, recomputed counts, required checks, identity controls, profile, candidate and freshness. A report's self-declared boolean is not evidence. Require and validate runner metadata; a hash beside the same editable file is not independent provenance. |
| E03 | P1, reproduced: the actual predicate in `25b_security_post_stress.sh` accepts overall BLOCKED with all checks blocked. | Use a shared validator supporting an explicit required postcheck subset. Reject BLOCKED/ERROR/SKIPPED required checks, missing artifacts and failed subprocess execution. Preserve precheck/load failures through finalization. |
| E04/E05 | P1, reproduced: `run_suite_y` accepts `{}` as A's positive equipment control; B's control also accepts empty JSON. | Require the expected schema, nonempty independently seeded own-object/canary, and verified identity/scope. Identical-looking empty, absent-route or generic deny responses must not establish a useful positive control. |
| E06 | P1, reproduced: B→A returns PASS on a 403 containing A's canary. | Apply the same body/schema/canary/leak checks in both directions and across every protected endpoint. A deny status does not excuse private data in its body, headers or download. |
| E07 | P1, reproduced: viewer mutation check accepts 401 as role-denial proof. | Confirm viewer identity and permitted read first; require the documented authorization-denial response. Invalid/expired login is a separate authentication case, never viewer-role proof. |
| E08 | P1, reproduced: `scripts/qualification/zap_baseline_verdict.py` accepts `{"site": []}` as a passing scan. | Require expected origin, actual traffic/coverage statistics, completed jobs, valid report structure and supported severity values. Zero sites/requests, a login-only crawl, malformed alerts or scanner errors cannot qualify. |
| S01 | P1, source: `suites/__init__.py` falls back from operator A to admin; `_login_me` tolerates missing subject/role and does not compare configured tenant IDs. Mapping/datasets foreign checks lack corresponding own-route controls. | Remove identity substitution. Verify actual subject, role, membership and selected tenant; retain tokens only after successful verification. Bind each negative check to its own positive fixture/control. |
| S02 | P1, source: `zap/af_plan.yaml` includes OpenAPI, passive wait and report, but no activeScan or verification tests; failOnError is false. The shell runner can accept a passive fallback/nonzero ZAP exit with a report and zero High alerts; its verdict ignores Medium policy. | Name passive coverage accurately. Deliver separate authenticated active qualification on disposable candidates, verify authenticated requests and per-job completion, and apply one explicit alert-disposition policy. Reduced fallback coverage stays incomplete. |
| S03 | P1, source: the ZAP runner stores `admin.jwt` under the artifact tree, makes directories broadly writable, and the Wave C workflow uploads that tree. | Use cryptographically random disposable secrets, private temporary storage and least-privilege scanner file access. Exclude tokens, rendered secret config, session databases and unredacted request logs from uploads; redact before archive and test with planted synthetic secrets. |
| S04 | P1, source: `run_suite_mqtt_acl` and gate 26 are stubs. Existing `mqtts_transport_isolation.sh` tests manually authored legacy site ACLs, not generated tenant ACLs. Its cross-site deny accepts absence of delivery without proving the foreign-topic observer was healthy. | Reuse and extend the real-broker fixture. Test actual generated tenant ACLs and certificate kits with positive observer controls before/after each denial. Keep transport health, certificate trust and authorization as separate assertions. |
| S05 | P1, source: local docs specify plaintext HTTP. `Caddyfile.react.http` has `auto_https off`; Compose Caddy publishes port 80. Legacy central/standalone recipes publish API on all interfaces by default. | Implement a documented standalone HTTPS profile with trusted certificates, renewal and safe bootstrap. Restrict direct API/web ports and prevent proxy bypass. Preserve central's existing `assert_bind_auth_policy`; do not misreport it as globally auth-disabled. |
| S06 | P1, source: fieldbus image defaults to HTTP `0.0.0.0`; `auth.rs` bypasses auth when the key is absent, and startup has no equivalent non-loopback refusal in the inspected path. Normal Compose overrides HTTP to loopback, but alternative image/host-net launch can differ. | Default management to loopback and require explicit secure management configuration/auth for remote access. Test raw image launch and every recipe, missing-key startup, public exclusions, IPv6 and direct paths. Health can remain lean; OT action routes cannot inherit a silent open mode. |
| S07 | P1, source: broker entrypoint applies `chmod a+r` to the server private key. Provisioner uses ordinary file writes for keys and tenant-independent kit directory/CN identity based on site/edge. | Enforce private key ownership/modes without world readability; test writable/read-only mounts. Make provisioned identity/storage injective across tenant/site/edge or enforce/document global uniqueness. Generate same-label tenant fixtures and prove no overwrite or merged ACL permissions. |
| S08 | P2, source: central and fieldbus final Docker stages have no USER; most Compose services lack the hardening controls present on Caddy. AppSec runs cargo-audit, Gitleaks and Trivy filesystem scanning, not an explicit scan of every released image digest. | Audit runtime UID/capabilities/mounts/resources and harden per service without breaking required BACnet networking or persistence. Scan final images and SBOMs, including amd64/arm64 artifacts where shipped, in addition to source dependencies. No CVE claim from base-image names alone. |
| S09 | P1, source: login throttling takes the first `x-forwarded-for` value in `routes.rs::auth_login`; nginx appends the incoming chain. Trusted-edge sanitization was not verified. | Test through Railway and standalone proxy chains in isolated equivalents; use a defined trusted-proxy policy and peer identity. Prove spoofed forwarding headers cannot reset limits or inject audit identity; do not blindly trust arbitrary client header strings. |
| S10 | P2, source: suite Z checks only CSP presence, probes CORS on public health, and counts the harness's own redirect behavior as a deployment check. `SafeHttpClient` checks overall deadline only between requests and uses socket inactivity timeouts while reading. | Test policy semantics on relevant responses, real browser behavior, and separate client safety from app security. Add deadline/cancellation tests for slow-drip bodies, sleeps/retries and cleanup; validate finite positive budgets. |
| S11 | P1/P2, source: inspected workflows do not explicitly run `tests/security` or `tests/qualification`; Wave C PR tests can use an older base/fallback image. No Nessus qualification workflow was found. | Wire named evaluator and real-app checks into CI, verify required-job execution, and distinguish harness regression on a reference image from qualification of the actual candidate. Add the Nessus workflow in section 7. |
| S12 | P2, source: the Cursor harness brief still says the harness/gates do not exist; agent context has mixed historical wave labels, while takeover docs point to Wave T. | Consolidate authoritative current instructions and make stale context detectable. Preserve historical records as historical, and avoid a second competing security master. |

Also inspect actual loaded ACL paths: broker configuration reads `/mosquitto/certs/acl`, while multiple Compose files additionally mount an ACL at `/mosquitto/config/acl`. Validate the effective configuration; editing an unused mount is not remediation. `TopicBuilder::edge_acl_patterns` already limits publishing to telemetry/metadata/discovery/status/acks; preserve that stricter contract rather than copying permissive legacy example `#` rules.

## 4. Upgrade Python, browser and ZAP assurance

### A. One control matrix with real evidence

Use versioned OWASP ASVS 5.0.0 requirements, aiming at applicable Level 2 controls with risk-selected stronger controls for tenant administration, provisioning and OT command paths. Pin WSTG references. Map requirement → profile → route/method/selector → implementation → independently expected result → fixture → automated/manual check → evidence. Do not invent requirement IDs or call an incomplete matrix ASVS certified.

Generate/check route inventory from actual registered central, fieldbus and MCP surfaces and reconcile OpenAPI/browser traffic. The current regex inventory extractor is limited; test nested routers, methods and feature flags or use a structured registration/OpenAPI source. A registry listing a check ID is distinct from that check running successfully on a candidate. Unknown access policy remains an explicit issue, not the current behavior copied into expected results.

Expand A/B/operator/viewer/scoped-agent/hub-admin/vendor and multi-membership/revoked-user cases over tenants, datasets, mappings, model JSON/TTL/SPARQL, FDD results/config, analytics, export jobs/downloads, histories, attachments, engineering evidence/calculations, budgets, user administration, provisioning and command routes. Test selectors in path/query/body/headers, omitted/duplicate/conflicting selectors, object existence and same labels across tenants. Confirm unauthorized writes have no stored side effect using independent state reads. Reuse the model/ECM handoff and Wave T model gate where applicable.

Authentication/JWT cases should cover the actual algorithm allowlist, signature/tampering, malformed claims, expiry and valid sibling, applicable nbf/issuer/audience policy, role escalation, minting scope, account disable/password change, session/logout behavior and key rotation. Use controlled isolated signing keys or server-issued short-lived test tokens; do not extract live signing secrets. The current CLI does not establish a documented isolated-secret provisioning path; make that path reproducible. Document what logout/revocation promises for issued JWTs and test that contract.

Add bounded isolated account-enumeration/throttling tests, concurrent grant changes, stale sessions/cache reuse, replay and duplicate job submissions. Review trusted proxy headers, secure password transport/storage and reset/account lifecycle. Never make successful tenant access depend on an admin fallback. Fail verified identity errors before using that session further.

Classify and exercise applicable XSS/DOM sinks, unsafe render/export content, archive traversal and decompression limits, SQL/SPARQL/template/command injection boundaries, SSRF/import URL handling, arbitrary file access, prototype/mass assignment behavior, oversized bodies and work queues. Prefer app-specific fixtures and interpretable expected outcomes over adding many generic payloads. Use isolated callback sinks and blocked outbound networking where needed. Do not submit test payloads to OT drivers or real building controllers.

Use the existing browser test stack for login, account switching, logout/back-button/cache, local/session storage, tenant UI state, downloads and XSS execution detection. Test CORS on protected responses and preflights with a real browser; public health allowing anonymous cross-origin reads is not automatically a private-data vulnerability. Determine CSRF applicability from actual cookie/Bearer credential behavior and route effects. Header presence alone does not prove CSP strength, HSTS transport protection or browser enforcement.

### B. Evaluate the tools before trusting their results

Make E01–E08 permanent regressions and extend deliberately broken fixtures with wrong identity/membership, expired sessions, foreign data in deny responses, absent routes, unrelated-schema 200s, wrong-method responses, failed cleanup, auth loss midscan, slow responses, corrupted/stale/duplicate reports and missing required IDs. Prove the detector fails for the intended defect and passes its corrected sibling. Run these tests in a fresh environment and in required CI jobs, followed by real Rust middleware/storage/proxy tests on the candidate.

Produce machine-readable per-check outcomes with candidate commit/image digest, scanner/harness/config versions, profile, fixture and model revisions, identity aliases, request/response schema fingerprints, timestamps, budgets, observed request counts and artifact hashes. Recalculate aggregate status from validated checks. Require expected subject/tenant and own-object canaries without recording tokens or private response bodies. Separate harness self-tests from tested application controls in the coverage denominator.

Dry-run performs no DNS, socket creation or credential loading. Mutation and resource-abuse checks require an isolated profile with disposable fixtures and cleanup. The existing live-readonly suite attempts a viewer token-mint POST; a broken server can make that succeed and mint a token. Move such potentially successful writes to an isolated profile, or define a narrowly authorized canary-mutation profile with observable cleanup. Do not label a run read-only merely because it expects denial.

### C. Authenticated ZAP and exploratory review

Keep public passive baseline as one limited layer. Build a separate ZAP Automation Framework plan with verified authentication, correct context/origin scoping, route/schema import, browser/client exploration where needed, explicit bounded activeScan policies, job tests and completion/traffic coverage checks. Use per-user sessions for tenant A, B, viewer and admin as applicable. Import alone does not prove protected endpoints were reached; assert known authenticated responses and minimum required method/route coverage through ZAP.

The existing `ZAP_AUTH_HEADER_VALUE` mechanism is supported by ZAP; retaining it is acceptable if configured and tested correctly. Restrict header injection to the intended target site, prevent redirects from disclosing credentials, and monitor logged-in/logged-out/auth-error statistics. A token minted outside ZAP does not prove the scanner remained authenticated. Test an expired token and a fake-login-200 fixture to ensure the run fails coverage. Enforce job errors, auth failures, deadlines, target restrictions and scanner-version/add-on policy. Medium dispositions need scoped findings, rationale, owner and expiry; neither fallback nor a broad accept flag can erase missing coverage.

Run active/fuzz/race tests on a disposable web+central equivalent with OT integrations disabled and unreachable. A Railway staging application must use separate data/credentials/broker resources and have no command path to live fieldbus. Keep exploratory Kali/Burp review for new workflows, abuse chains and unmodeled business logic; convert discoveries into deterministic regressions after private triage.

If claiming improvement over a human Burp session, benchmark the same seeded known-defect corpus and workflows: route/role combinations, detection/false-negative rate, false positives, elapsed time and repeatability. Include an independent holdout set and a reviewer who did not author the tests. Limit the claim to that benchmark. No request-count or green-test-count metric alone measures security expertise.

## 5. Secure standalone bootstrap and fieldbus deployment

Deliver a supported local HTTPS installation that does not require the next operator to invent an external reverse proxy. Evaluate enabling TLS in the packaged Caddy front end versus another existing supported terminator; document the chosen implementation. Support customer/internal CA certificates with SAN/hostname validation, key permissions, renewal/expiry monitoring, browser and scanner trust, and offline deployment where public ACME is unsuitable. TLS 1.2+ with a current policy, HTTPS-only authentication, and an optional HTTP-to-HTTPS redirect are the target; never use `--insecure` or disable scanner checks to hide certificate problems.

Keep central private, web accessible through the chosen entry point, fieldbus management loopback by default, and MQTT exposed only as the topology requires. All non-loopback production management/API access needs authentication and protected transport. Retain a clearly separate loopback development profile; it cannot satisfy standalone production qualification. Normalize bootstrap validation across recipes, including missing/default secrets, `OPENFDD_ALLOW_OPEN_BIND`, API keys, certificates and required ACL files. An IP firewall alone does not encrypt a login on an OT LAN.

Verify actual socket exposure from an approved peer as well as host inspection; `docker ps` and localhost checks are insufficient. Test IPv4/IPv6 and the Docker firewall backend. Docker bridge port publishing can bypass ordinary UFW handling, while host-network fieldbus uses the host network directly. Document the supported firewall path and prove it with expected allowed and denied connections. Do not globally disable Docker firewall rules or change live host firewall settings merely to make the tests work.

Harden each released image/runtime: dedicated UID/GID where feasible, minimal capabilities, no-new-privileges, read-only root where practical, explicit writable data/spool/tmp mounts, no Docker socket, bounded logs, resource/PID limits and restart behavior. Host networking needed for BACnet is not justification for privileged containers. Preserve vendor interoperability, fixed production polling policy and explicitly required UDP behavior while testing limits on malformed traffic only in the emulator/lab.

Fieldbus auth should fail closed for remote management without a strong configured key; use a secured management path for intentional remote administration. Inventory GET routes that trigger discovery or other OT activity as effects, not automatically safe reads. BACnet/IP itself does not gain HTTP authentication from securing port 8081: document approved BMS peers, network segmentation and hosted commandable point behavior. Require isolated negative tests for unauthorized HTTP operations and simulated BACnet/command writes without touching physical equipment.

## 6. MQTTS identity, authorization and command boundary

Use the real provisioner, `TopicBuilder`, Mosquitto image/entrypoint and intended ACL-loading path in integration fixtures. Include multiple tenants with identical site/edge labels, multiple edges within one building, scoped central identities and certificate rotation/revocation. Confirm connection auth separately from publish and subscribe authorization. Reject anonymous/no-cert, wrong CA, wrong hostname, expired certificate and other invalid identity cases; configure TLS versions/ciphers/EKU and certificate lifecycle deliberately.

Prove permitted telemetry delivery and permitted command subscription before testing foreign/wildcard denial. Verify the observer is alive and can receive a B canary before/after A→B denial; timeout/no-message alone is not proof. Exercise own/foreign publication and subscription, `+`/`#`, `$SYS`/shared subscriptions where supported, retained messages, duplicate client IDs, reconnects and session persistence. Include negative edge publication to command topics and unauthorized command acknowledgments.

Broker topic ACLs do not replace application validation of topic versus payload tenant/building/edge identity. Test that mismatch, enrollment/kit download scope and deletion/revocation. Preserve current retained-command rejection, expiry and duplicate-ID guards; test replay after restart, identity matching, response-topic restrictions and actual authorization for each command kind. Decide/document whether telemetry-only deployments disable command subscriptions entirely. Never rely on outbound-only TCP as proof that cloud compromise cannot affect OT.

Enforce restrictive private-key modes at creation and runtime, unique tenant identities, minimal downloaded kit contents and protection of CA/central keys. Do not solve broker access by making keys world-readable or distributing a shared fleet identity. Prove revocation both at new connection and existing session according to a documented maximum window. Repair the automated fixtures' own broad file permissions as well.

The cloud broker profile must require broker identity/ACL evidence. Gate 26 can be N/A for a genuinely broker-free CSV installation; a disabled flag or unimplemented fixture is not sufficient for a full cloud-plus-fieldbus security claim. Keep Railway application qualification and full pipeline qualification distinct while broker work remains incomplete.

## 7. Add actual Nessus readiness and assessment

Yes, qualify a standalone deployment on an isolated Linux VM/host using the same immutable released images and deployment configuration, with synthetic data and simulated/disconnected OT. Run the scanner on another machine such as the Kali test bench or a dedicated scanner VM, with a licensed, supported Nessus edition and updated plugin feed. Use the edition's supported scan policy/export mechanism; do not assume `nessuscli` is a general scan-launch CLI. Do not install a scanner into the production application containers.

Provide versioned, secret-free policy templates/checklists and a report importer, for example a reusable `scripts/security/nessus/` toolset plus local/fieldbus fixture manifests. Choose actual final paths after inspecting existing conventions. Include:

1. External network/service assessment from the approved LAN/management perspective, confirming expected open and restricted ports, HTTPS and MQTTS certificate/TLS policy, no plaintext management bypass, and no unexpected admin services.
2. Credentialed Linux host assessment with a dedicated scanner account and the privileges required by the selected checks, governed by the operator's credential policy. Cover host packages/kernel, SSH, Docker daemon, file permissions and relevant compliance checks. Record successful credentialed-check evidence such as plugin 19506 and scan completeness; a login attempt alone is insufficient. Never add SSH to every application container for scanning.
3. Separate final-image dependency/SBOM assessment for central/web/mqtt/fieldbus/MCP and the chosen front end. Host scans are not evidence that all image layers/application dependencies were assessed. Preserve architecture/digest and vulnerability-database timestamps; triage actionable findings and rebuild/rescan rather than trusting moving tags.
4. Container runtime/deployment configuration checks, which must distinguish a required hosted BACnet service from an unintended Internet-facing management port. An open port may be legitimate but must have a documented boundary and applicability, not a blanket waiver.
5. Remediation/rescan linkage per Nessus plugin/finding: target alias, port/protocol, evidence, affected package/config, candidate, action, owner, disposition, expiry and retest outcome. Preserve the native `.nessus` report privately and produce a redacted summary.

Define the acceptance policy before scanning with the intended customer's IT/security requirements: zero unresolved Critical/High findings as a default release gate, Medium reviewed with justified time-bounded disposition, and stricter requirements where requested. Explicitly distinguish vulnerabilities, configuration/compliance failures, false positives and informational findings. No blanket exclusions, scanner-source-only allowlists that conceal exposure, disabled TLS checks, fake banners or suppressed findings to manufacture a pass. Necessary scope exclusions mean untested coverage, not closed ports or no vulnerabilities.

Nessus can identify OT services and stop further scanning when its OT-device setting is disabled. For a Linux Open-FDD host running a hosted BACnet service, verify that intended host/app checks actually ran; zero alerts after an OT early-stop is not a clean assessment. Use an isolated representative target to resolve this safely. Keep Safe Checks enabled initially, low concurrency and stop-on-unresponsive behavior; those settings do not guarantee safety for every physical controller. Never scan a whole production OT subnet or enable invasive OT tests as an automatic step. Active Nessus/BACnet testing needs a defined lab target or a separately authorized site window and recovery plan.

Report import must validate supported format, scan completion, scanner/plugin-feed version, expected target/profile/ports, credentialed coverage, candidate mapping, timestamps, source hash and accepted exclusions. Reject missing/empty/unrelated/stale/truncated scans and failed credentials; absence of alerts alone cannot PASS. Harden XML parsing and file-size/path handling. Evaluate the importer using synthetic failing, clean, incomplete, foreign-target, stale and malformed reports. Missing licensed scanner/report stays BLOCKED; Python/ZAP/Trivy output cannot be renamed Nessus evidence.

Railway qualification assesses the application's authorized public origins and deployed image supply chain. Do not scan Railway's shared provider address space or assume host-level SSH/compliance access to Railway infrastructure. Separate operator-controlled settings from provider-managed controls and retain any provider evidence separately.

## 8. Stress integration and durable developer context

### Stress and release gates

Keep these layers distinct and required where applicable:

- Each relevant PR: evaluator sabotage tests, route/profile/schema drift, security/qualification unit tests, applicable real Rust and browser security tests, and dependency/secret scanning. Verify the required CI jobs actually invoke the new tests.
- Isolated candidate: authenticated ZAP, write/race/upload/abuse cases, real generated MQTT ACL tests, standalone TLS/port/runtime tests, and Nessus assessment when a deployment/runtime/security change invalidates prior evidence.
- Each scheduled applicable stress run: authenticated fixture preflight and bounded regression checks, monitored workload, and postchecks finalized even on error. Record candidate and fixture identity at both ends. Public baseline remains limited passive evidence. Resource/cancellation/cleanup failures are visible failures.
- Approved Railway milestone (currently Wave T T3): integrate completed web/model/ECM security checks with gates 25/25b and pipeline ACL evidence where required. Do not start a full live run from every child or reuse old report files to qualify a new pin.

Nessus and active ZAP need not run against live OT on every generic validation loop. Define freshness and invalidation rules: image/base dependency, TLS/proxy/exposure, auth, broker/ACL, host update and configuration changes trigger affected rescans; scheduled reassessment also captures updated vulnerability feeds. Reused evidence must match a documented allowed scope and still-valid candidate/config, with lineage visible in the manifest. Large stress campaigns do not compensate for omitted control tests.

Use monotonic global deadlines, bounded retry/backoff/rate/concurrency and explicit cleanup reservations. Test cancellation inside slow operations, not only before the next request. Keep post-stress auth rate-limit recovery separate from evidence that throttling itself works. Monitor ingest/FDD latency, spool growth, reconnects and command activity without modifying live BAS values.

### Portable AI/human handoff

Maintain one short security entry point (extend `docs/operations/TESTBED_TAKEOVER.md` or a clearly linked canonical security runbook) with the three profiles, supported threat/control matrix, prerequisites/versions, image acquisition, fixture creation, env-reference setup, dry-run/offline/isolated execution, report reading, cleanup, update/rollback and incident/reporting path. `.cursor/agents/openfdd-security-python-harness.md` should be a thin accurate instruction entry, not a duplicated historical implementation plan. Link the canonical contract from root/fieldbus AGENTS and relevant skills.

Replace author-specific paths and deployed site names in portable commands with repo-root discovery, aliases and validated config. Keep actual deployment pins/hosts/credentials/private pending findings in an access-controlled operator record outside public docs; distinguish historical logs clearly. Public docs can explain topology and how to test safely without publishing real inventories, scanner output or unresolved exploit walkthroughs. Test for accidental secrets in plan files, generated configs, logs, browser traces and CI archives. Do not delete useful public security documentation to pursue secrecy.

Add a doctor/preflight command that checks required versions, scanner availability, profile schema, certificate trust, image digests, fixture readiness and paths without printing or loading secrets during dry-run. Explain license/manual steps honestly. A fresh-clone exercise on another developer environment must create its own synthetic fixtures/secrets, run offline detector tests, deploy the isolated profile from qualified images, execute the applicable tests, produce validated evidence and clean up without chat memory or maintainer-only paths. Record this takeover exercise as an acceptance artifact.

## 9. Completion criteria

- [ ] E01–E08 have permanent regressions and correct rejection behavior; existing tests still pass.
- [ ] Every S finding has current source evidence, an isolated test where needed, a fix or a justified remaining limitation.
- [ ] Runtime identity/route/method/control coverage is explicit; omitted/blocked policy and scanner failures cannot qualify.
- [ ] Required evaluator, real-app and browser security jobs run in CI; candidate tests cannot silently fall back to old images.
- [ ] Three deployment profiles have executable exposure/auth/TLS configuration checks; fieldbus remains off cloud and inaccessible from unauthorized networks.
- [ ] Authenticated active ZAP proves login and endpoint coverage; passive/fallback coverage is labeled accurately.
- [ ] Actual generated tenant MQTT kits/ACLs, certificate lifecycle and command boundaries are qualified on isolated fixtures.
- [ ] Standalone and fieldbus host Nessus workflow, validated import, image scans and remediation/rescan records exist; actual unrun Nessus work remains BLOCKED.
- [ ] The next maintainer can execute the documented isolated workflow without private chat history; public artifacts pass redaction checks.
- [ ] Applicable stress profiles consume validated pre/during/post evidence on the correct candidate, with cleanup and resource bounds proven.

Deliver requirement → implementation → command/test → candidate/config/fixture revision → artifact → PASS/FAIL/BLOCKED/justified N/A. Summarize exactly what was tested, how false positives/negatives were evaluated, and what remains for expert review. No “Nessus certified,” “fully secure,” or “better than an expert at everything” label.

## Primary references checked for this review

- [OWASP ASVS](https://owasp.org/projects/asvs) — versioned control requirements; use actual requirement IDs.
- [OWASP WSTG business-logic testing](https://wstg.owasp.org/v4.2/4-Web_Application_Security_Testing/10-Business_Logic_Testing/00-Introduction_to_Business_Logic/) — application-specific abuse cases and expert review.
- [ZAP AF authentication](https://www.zaproxy.org/docs/desktop/addons/automation-framework/authentication/) and [target scanning issues](https://www.zaproxy.org/docs/getting-further/automation/target-scanning-issues/) — supported header authentication, verification and scan statistics.
- [ZAP activeScan job](https://www.zaproxy.org/docs/desktop/addons/automation-framework/job-ascan/) and [monitor tests](https://www.zaproxy.org/docs/desktop/addons/automation-framework/test-monitor/) — explicit active policy and failure monitoring.
- [Tenable discovery settings](https://docs.tenable.com/nessus/Content/DiscoverySettings.htm) and [advanced settings](https://docs.tenable.com/nessus/Content/SettingsAdvanced.htm) — scope, OT detection/early-stop, and scan safety settings.
- [Tenable credentialed Linux checks](https://docs.tenable.com/nessus/Content/CredentialedChecksOnLinux.htm) and [plugin 19506](https://www.tenable.com/plugins/nessus/19506) — privileged assessment and scan-information evidence.
- [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/) — published ports, UFW interaction and host-network differences.

These references guide the required work; they are not evidence of a completed Open-FDD assessment.
