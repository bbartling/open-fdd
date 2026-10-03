# Open-FDD milestones

This is the release-outcome index. [Wave U master](docs/operations/WAVE_U_MASTER.md) owns historical FQ/ops pins; [BUG_REPORT_WAVE_P](docs/operations/BUG_REPORT_WAVE_P.md) owns bugs and evidence. **Active product patch train (2026-10-03):** [`.cursor/plans/patch_all_open_issues_master.plan.md`](.cursor/plans/patch_all_open_issues_master.plan.md). Historical migration milestones remain under `docs/migration/` and `openfdd_agent_spec/`.

## Status rules

- **PLANNED / IN PROGRESS:** requirements or implementation remain.
- **PARTIAL / REOPENED:** useful work exists, but acceptance evidence is incomplete or contradicted.
- **BLOCKED:** name the external dependency, owner and next action; continue independent work.
- **VERIFIED:** all exit criteria passed on the identified candidate/profile with reviewable evidence.
- **RELEASED:** verified candidate published/deployed as applicable, with rollback and handoff recorded.
- **DEFERRED:** explicitly agreed scope/date/owner. Never use cancellation to hide an unmet requirement.

A merged PR, a passing unit suite, a completed scan, and a verified deployment are different achievements. Record them separately. No milestone becomes VERIFIED from an old pin, skipped test, changed threshold or unreviewed exception. Actual licensed Nessus results are separate from readiness work that needs no license. Cursor/Codex local `pytest` is not a Grok live security PASS.

## Mega patch train — all open issues (2026-10-03) — IN PROGRESS

**Plan:** [`.cursor/plans/patch_all_open_issues_master.plan.md`](.cursor/plans/patch_all_open_issues_master.plan.md)  
**Spec:** [`openfdd_agent_spec/PR_PROTOCOL.md`](openfdd_agent_spec/PR_PROTOCOL.md) (local compile before push; agent takeover) · [`openfdd_agent_spec/AGENTS.md`](openfdd_agent_spec/AGENTS.md) rules **0b** / **0c** / **60** / **60d** · skill [`openfdd-mt-security`](openfdd_agent_spec/skills/openfdd-mt-security/SKILL.md)  
**Tip (MT branch, not OPS pin):** **3.5.61** on `fix/mt-isolation-csv-sites-1088-1090`  
**Operator intent:** one IDE owns the entire train (Codex out of API budget). Finish former Codex security draft [#1102](https://github.com/bbartling/open-fdd/pull/1102) instead of excluding it. Local `cargo`/`npm`/`pytest` before Actions. Final GHCR refresh, then **Grok bot** owns live stress + security pen-test of the policy/harness and issue closeout comments. **No FQ / OPS pin from mid-wave tips.**

### Ownership split

| Actor | Owns |
| --- | --- |
| **Cursor (this IDE)** | Implement + local verify + merge all open-issue PRs including #1102 takeover; mid-wave smoke only |
| **Grok bot** | After GHCR tip: OT MEGA / hub stress, gates **25**/**25b**/**26**, live security qualification policy + pen-test Python scripts, evidence comments / issue closes |
| **Kali** | Staging ActiveScan / OT when scheduled (Mint does not ActiveScan OT) |
| **External** | Licensed Nessus assessment (**U-H**) — BLOCKED without license; Soft-OPEN, not a tooling merge blocker |

### Wave / issue tracker (18 open issues at train start)

| Wave | Issues | Vehicle | Status |
| --- | --- | --- | --- |
| **A — MT isolation** | #1088 #1089 #1090 → then #1087 | **PR-01** `fix/mt-isolation-csv-sites-1088-1090` (tip **3.5.61**) — local cargo/vitest green; opening for Actions; **PR-05** after PR-01 | **IN PROGRESS** — list allowlist leak + Sites chicken-egg + `get_edge` ACL |
| **B — docs / research** | #998 #985 #1009 | [#1105](https://github.com/bbartling/open-fdd/pull/1105) C1/#998 · [#1103](https://github.com/bbartling/open-fdd/pull/1103) ECM/#985 (keep issue open help-wanted) · [#1104](https://github.com/bbartling/open-fdd/pull/1104) water/#1009 | **IN PROGRESS** — PRs open (ready); Actions queued / not yet green |
| **C — security tooling** | #999 | [#1102](https://github.com/bbartling/open-fdd/pull/1102) Cursor takeover · undrafted · branch `security/post5d-profile-qualification` · local `pytest tests/security` passed | **IN PROGRESS** — Actions queued; **Grok** live pen-test after GHCR |
| **D — Haystack RDF** | #997 #1000–#1004 | **PR-07…11** = C2→C6 after [#1105](https://github.com/bbartling/open-fdd/pull/1105) merges; #997 last; HR-10 Option B (honest UNAVAILABLE) | **PLANNED** |
| **E — DataFrame + agent rules** | #1078 #1010 | **PR-12** (may stack I1/I2/I3) | **PLANNED** |
| **F — historian / hisRead** | #1017 | **PR-13** L1 ADR → L2 replay → L3 hisRead + 7d bench writeup | **PLANNED** (Phase 5D split already landed; durability remains) |
| **G — MQTTS field prove** | #1070 | **PR-14** ≥24h window `reports/gate39_window_20261003/`; code only if tip defect | **IN PROGRESS** (wall-clock) |
| **Final** | — | Merge train → GHCR newest-by-created → Grok MEGA / closeouts | **PLANNED** |

### Issue → PR map (all 18)

| Issue | PR / vehicle | Track | Notes |
| --- | --- | --- | --- |
| #1088 #1089 #1090 | **PR-01** | A | Tip **3.5.61**; local verify green; PR for Actions (do not merge until CI green) |
| #1087 | **PR-05** | A | After PR-01 |
| #998 | [#1105](https://github.com/bbartling/open-fdd/pull/1105) (PR-02 / C1) | B | Haystack C1 baseline |
| #985 | [#1103](https://github.com/bbartling/open-fdd/pull/1103) (PR-03) | B | ECM docs; **keep issue open** help-wanted |
| #1009 | [#1104](https://github.com/bbartling/open-fdd/pull/1104) (PR-04) | B | Water/chiller FDD research |
| #999 | [#1102](https://github.com/bbartling/open-fdd/pull/1102) (PR-06) | C | Cursor takeover; undrafted; Actions queued |
| #1000–#1004 + #997 | **PR-07…11** | D | Haystack C2–C6; #997 last |
| #1078 + #1010 | **PR-12** | E | DataFrame + agent custom rules |
| #1017 | **PR-13** | F | Historian + hisRead |
| #1070 | **PR-14** | G | ≥24h MQTTS prove; window open |

### Wall-clock waves

```text
Wave 1: PR-01 + #1105/#1103/#1104 + finish/merge #1102 ; #1070 window open
Wave 2: PR-05 + HR C2 + PR-12 start + historian L1
Wave 3–5: HR C3–C6, DF, historian L2/L3, gate39 evidence
Final: GHCR refresh → Grok MEGA
```

### Subplans (`.cursor/plans/`)

- Master: [`patch_all_open_issues_master.plan.md`](.cursor/plans/patch_all_open_issues_master.plan.md)
- PR-01 MT: [`pr01_mt_isolation_1088_1089_1090.plan.md`](.cursor/plans/pr01_mt_isolation_1088_1089_1090.plan.md)
- PR-03 ECM: [`pr03_community_ecm_985.plan.md`](.cursor/plans/pr03_community_ecm_985.plan.md)
- PR-04 water: [`pr04_water_fdd_research_1009.plan.md`](.cursor/plans/pr04_water_fdd_research_1009.plan.md)
- PR-05 CSV UX: [`pr05_csv_tenant_ux_1087.plan.md`](.cursor/plans/pr05_csv_tenant_ux_1087.plan.md)
- PR-06 / #999: [`pr06_security_scan_tooling_999.plan.md`](.cursor/plans/pr06_security_scan_tooling_999.plan.md)
- PR-12 DF/rules: [`pr12_dataframe_agent_rules_1078_1010.plan.md`](.cursor/plans/pr12_dataframe_agent_rules_1078_1010.plan.md)
- PR-13 historian: [`pr13_historian_haystack_1017.plan.md`](.cursor/plans/pr13_historian_haystack_1017.plan.md)
- PR-14 gate39: [`pr14_gate39_mqtts_prove_1070.plan.md`](.cursor/plans/pr14_gate39_mqtts_prove_1070.plan.md)
- Final GHCR→Grok: [`pr_final_ghcr_grok_handoff.plan.md`](.cursor/plans/pr_final_ghcr_grok_handoff.plan.md)
- Haystack wrapper: [`pr_haystack_rdf_track_wrapper.plan.md`](.cursor/plans/pr_haystack_rdf_track_wrapper.plan.md) · C1–C6: [`wave_haystack_rdf_c1_baseline_profile.plan.md`](.cursor/plans/wave_haystack_rdf_c1_baseline_profile.plan.md) … [`wave_haystack_rdf_c6_candidate_rollout.plan.md`](.cursor/plans/wave_haystack_rdf_c6_candidate_rollout.plan.md)

### Exit criteria (train-level)

- [ ] All 18 issues closed **or** Soft-OPEN with linked evidence / standing invitation (#985 help-wanted may stay open by design).
- [ ] #1102 merged (tooling); Soft-OPEN licensed Nessus remains under U-H.
- [ ] Local verify green on each product tip before push (rule **0b**).
- [ ] `master` Actions green; #1102 no longer draft/open after merge.
- [ ] GHCR tip refreshed via `./scripts/ghcr_newest_by_created.py` (not tag-name sort).
- [ ] Grok handoff packet recorded; no `fully_qualified=true` / OPS pin claim unless a real MEGA says so.
- [ ] Spec/SESSION_LOG/skills updated for MT ACL list semantics and Grok security ownership.

### Soft-OPEN (do not greenwash)

- Licensed Nessus (U-H) · full Haystack RDF HR-01–HR-12 evidence · DataFrame parity gate · historian 7-day hot-tier decision · ACME gate39 ≥24h non-empty RTU/VAV ledger · any mid-wave tip without MEGA.

## Protocol connector qualification — Phase 5D — MERGED (2026-10-03 source)

Phase 5D closeout PR [#1101](https://github.com/bbartling/open-fdd/pull/1101) and Phase 5C [#1100](https://github.com/bbartling/open-fdd/pull/1100) **merged** to `master` (`db1a53b9` tip family). Residual live BACnet/Haystack qualification Soft-OPEN continues under the mega patch train (Wave F/G + OT bench) and U-B/U-C — not as an unmerged Phase 5D draft. Historical checkpoint text below is retained for evidence archaeology.

### Historical implementation checkpoint (pre-merge)

- [x] Added the fail-closed evaluator at
  `scripts/qualification/protocol_connector_qualification.py` with fixed
  `synthetic`, `image_recipe`, `bacnet_live`, and `haystack_live` stages.
- [x] Added offline negatives for empty, partial, stale, contradictory,
  forged-top-level, receipt-mismatch, historian-mismatch, prohibited-surface,
  observed-BACnet-write, and leaked-secret evidence.
- [x] Wired the existing split process/image/Compose gate to emit a bounded,
  redacted `image_recipe.json` when
  `OPENFDD_SPLIT_EVIDENCE_DIR` is set. The recorded local image IDs are not a
  GHCR manifest digest claim.
- [x] Added AppSec and Rust CI evaluator hooks, capability-ledger entry,
  runtime/ADR documentation, and this handoff record.
- [x] Local evidence on source `69350919`: evaluator selftest and eight
  qualification unit tests pass; the complete qualification unittest suite,
  capability ledger validation, shell syntax, and diff checks pass. Live PASS
  claims now require check-specific device/read-only/typed/restart/replay
  evidence; missing command, authentication, process-ownership, and historian
  prerequisites are explicitly fail-closed.

### Remaining acceptance gates

- [ ] Exact Phase 5C parent head is green and accepted by Astra; record its
  full SHA in the PR body before calling Phase 5D ready.
- [ ] CI split gate passes on the exact PR head and uploads/retains the
  machine-readable image/recipe evidence. GHCR image publication, SBOM,
  provenance, signing, and vulnerability results remain separate evidence.
- [ ] The cloud recipes remain zero-OT and the selected edge recipe starts
  only its selected connector, with live process/PID/socket checks.
- [ ] Read-only BACnet bench evidence for the configured device instance 5007
  is captured, or the stage is explicitly `BLOCKED` because the device was not
  reachable. No write, release, or unbounded discovery is allowed.
- [ ] Authenticated Haystack evidence is captured only from a verified secure
  local configuration (endpoint, catalog, and Basic/SCRAM mode). The possible
  Pi address is not assumed. Missing configuration remains `BLOCKED`.
- [ ] Haystack-to-Central committed receipt, canonical historian readback,
  replay/conflict, and restart-resume evidence are captured without secrets.
- [ ] Capability, operations, ADR, session log, and PR summary agree that the
  Haystack profile is manual-only; no automatic collection claim is made.
- [ ] All required Actions are green on the exact head and the PR is
  mergeable; Phase 5C/5D remain unmerged until the operator reviews the
  evidence.

The closeout verdict is **PARTIAL / Soft-OPEN** until the operational stages
are proven. Synthetic PASS is necessary but cannot substitute for image/recipe,
BACnet, or authenticated Haystack evidence. A `SKIP` or `BLOCKED` stage is
never a qualification pass.

## Protocol connector split — Phase 5B draft / process hardening checkpoint

The draft stacked PR [#1100](https://github.com/bbartling/open-fdd/pull/1100)
starts from accepted source SHA `94dfcc6e` and defines the process boundary for
`openfdd-bacnet-modbus` and `openfdd-haystack`. Phase 5A added shared identity,
recipe, authentication, and bounded telemetry-sink contracts in
`openfdd_connector_runtime`. Phase 5B adds the two separate Rust binaries,
profile-specific route surfaces, a split edge Compose example, and
process/cloud-negative tests. The split BACnet HTTP surface is an explicit
read/status/connector/scanner allowlist; writes, discovery, Who-Is/router,
compatibility aliases, and arbitrary Modbus reads are absent. The Haystack
profile requires an API key and configured endpoint. Separate Docker targets
contain one intended executable each, while the compatibility target remains
legacy-only. The gate starts both local binaries, awaits real health, checks
distinct hello identities/PIDs and live prohibited routes, inspects their
process-owned descriptors, resolves cloud Compose, and inspects built target
metadata. The legacy `openfdd-fieldbus` binary remains compatible. No GHCR
refresh, image publication, live bench, discovery, write/release, or merge
claim is made by this checkpoint.

## Protocol connector Haystack slice — Phase 5C1 partial / draft PR #1100

The branch now contains the bounded Rust Phase 5C1 contract and transport
slice from accepted Phase 5B SHA `b842f606`: a startup loaded trusted Haystack
catalog with immutable revision, typed about/catalog/navigation/current-read/
finite-history requests, private source-ref mapping, explicit scope binding,
and Basic/SCRAM HTTP with redirects disabled, explicit credentials, bounded
timeouts and streaming bodies. History values preserve genuine source
timestamps; the public contract does not accept URLs, Zinc filters, refs,
credentials, or navigation paths. Central exposes the same operations through
its authenticated configured-upstream proxy.

The BACnet/Modbus process local sink posts only to fixed authenticated
`/api/ingest/local`, parses one typed receipt shape, rejects missing tokens,
redirects, oversized bodies, and message-id payload conflicts, and keeps
Central as the sole historian writer. The standalone Haystack process has no
automatic polling producer; it validates `local_fieldbus` as a startup policy
and exposes a manually triggered current-read to authenticated local-ingest
route alongside the typed read surface. Receipts now distinguish
pending, committed positive, terminal zero-eligible, rejected, retryable, and
conflict outcomes, with a persisted envelope digest and exact scope/site/edge/
message correlation. `TelemetryPoint.observed_at` is optional for normal
telemetry and required in typed Haystack history values.

This is **PARTIAL**, not a delivery claim. Focused Rust checks are still being
completed; live authenticated Haystack application qualification, image/GHCR
publication, live OT bench work, deployment, merge, and FQ remain Soft-OPEN.
No direct Parquet/second database, UDP, write/release, caller-controlled
upstream, or Haystack MQTTS/dual activation was added.

## Protocol connector Haystack slice — Phase 5C2 hardening partial / draft PR #1100

The follow-up hardens the C1 boundary with real Zinc scalar normalization:
`Number.val`/`Number.unit`, canonical `HRef.val`, timezone-aware
`HDateTime.dt`, and `id == @ref` filters. Synthetic authenticated Basic and
SCRAM Zinc fixtures cover current/about/history reads, labels, units, source
timestamps, redirects, and chunked body limits. Response validators enforce
exact scope, scalar/unit safety, in-window history timestamps, and exact
sample counts.

The local sink now validates receipt scope/site/edge/message identity and
eligible/persisted counts before acknowledging. Terminal zero-eligible,
rejected, and conflict outcomes leave the retry queue through quarantine;
pending and retryable outcomes remain queued. Central oversize Axum extraction
returns a typed receipt, and point source timestamps reach the canonical
historian batch. The security route inventory covers all five Central
Haystack proxy paths.

This remains **PARTIAL**. The standalone Haystack process exposes its typed
read API and a manually triggered local-ingest path; automatic polling and
live vendor qualification remain Soft-OPEN. A loaded-catalog Zinc to typed
envelope to authenticated Central receipt and historian readback is covered
by synthetic bounded tests. Image or GHCR publication, deployment, merge, and
FQ remain Soft-OPEN.

The manual path persists each envelope before delivery and uses the caller's
request UUID as the durable message identity. Pending, retryable, timeout, and
uncertain responses retain the original payload in the bounded spool; a retry
of the same request resumes that payload and cannot mint a second message.
Synthetic HTTP coverage exercises the real split management bearer, Haystack
Basic bearer, Central ingest bearer, typed pending receipt, retry with the same
message/payload, committed receipt, and canonical historian readback.

## Operations protocol workspace Phase 4 — draft / source and read-only bench verified

**Owner path:** draft PR [#1099](https://github.com/bbartling/open-fdd/pull/1099),
branch `feat/protocol-workspace-phase4`, stacked on Phase 3D. The implementation
accepted source head is `79f157c916a9743b24d847c23ab2d3ea927ae617`.

### Landed in the draft branch

- Versioned bounded priority-history contract with exact P1–P16 snapshots,
  scope and request correlation, opaque cursor binding, and safe typed errors.
- Edge-local durable history store and opt-in scheduler. It visits one trusted
  configured device after each completed interval (default 3600 seconds,
  minimum 300), has no catch-up burst, and performs no discovery, write,
  release, or remediation action. History uses an append-only JSONL journal,
  periodic bounded checkpoints, file and parent-directory sync, and recovery
  tests for torn tails, corrupt non-tail entries, stale temporary files, and
  restart/cursor retention. Store failure disables history fail-closed without
  taking down core BACnet polling.
- Authenticated fieldbus and central history routes, capability/inventory
  advertisement, OpenAPI declarations, and a React panel that loads history
  only after an explicit capability-backed user action. An explicitly typed
  operator/admin trigger runs one bounded visit through the same non-overlap
  guard; viewers receive 403 before any upstream proxy or OT call.
- OT recipes persist `/edge-state`; `central` and `csv` remain cloud-only and
  contain no fieldbus/scanner service. MQTT history synchronization is deferred
  to a separately versioned future transport contract.

### Evidence and remaining acceptance

- Astra accepted exact SHA `79f157c916a9743b24d847c23ab2d3ea927ae617`.
  Rust format and warnings-denied Clippy passed, along with contract priority
  tests **7/7**, fieldbus priority tests **12/12**, and focused frontend tests
  **21/21**. Central route/auth, security inventory, Compose, and topology
  gates also passed locally.
- Frontend lint still reports pre-existing repository warnings when run with
  `--max-warnings=0`; this is a CI hygiene item, not silently treated as pass.
- Read-only BACnet bench qualification passed without replacing or restarting
  the existing healthy fieldbus container. A narrowed Who-Is found exactly
  device **5007** on its routed network. A separate Phase 4 binary used
  alternate local HTTP and hosted BACnet ports, MQTT disabled, a temporary
  edge store, and one configured AO target. Its first explicit trigger added
  exactly one record containing **16** priority slots. After a clean process
  restart, sequence 1 and the durable device cursor were restored before any
  new scan; a second trigger added one record and advanced history to sequences
  1 and 2. Responses reported read-only operation with discovery and writes
  disabled. No WriteProperty or release endpoint was called.
- GitHub Actions remain in progress, so draft PR #1099 is not yet fully green.
  No GHCR refresh, deployment, merge, or FQ claim occurred. The Haystack bench
  host answered reachability preflight, but authenticated Haystack application
  testing remains a later protocol-container qualification item.

## Wave U outcomes — acceptance snapshot 2026-09-20

The independent audit reopened acceptance checks. Statuses below do not erase earlier test runs or imply that existing improvements were absent. The snapshot covered #959/#960 merged and #961 in flight; consult GitHub and BUG_REPORT for later changes.

| ID / suggested GitHub milestone | Scope and owner | Status | Exit criteria |
| --- | --- | --- | --- |
| **U-A — Evaluated qualification** | Security/test maintainer | VERIFIED (evaluator contract on tip) | Permanent negatives + required gate 36s; MEGA `20260921T021332Z` `fully_qualified=true` on `sha-1677c33`. Standalone peer/image remediations remain under U-B/U-E. |
| **U-B — Standalone OT readiness** | Deployment/security maintainer | PARTIAL | HTTPS compose hide web:3000 + trusted-CA peer soak `20260921T023714Z`. Product-image candidate soak still required. |
| **U-C — Field gateway readiness** | Field/MQTT maintainer | PARTIAL | Field-only exposure + key modes + dual-tenant tests; BACnet CI RO key staging fixed in 3.5.38. Product MQTT image ACL Soft-OPEN. |
| **U-D — Web application assurance** | App/security maintainer | PARTIAL | Auth/tenant matrix on MEGA; authenticated ZAP candidate AF still Soft-OPEN. |
| **U-E — Image and host acceptance** | Release/deployment maintainer | PARTIAL | Tip rescan `sha-1677c33`; mqtt 0 H/C; web nginx force-upgrade in 3.5.38; Debian TRACKED UNFIXED; caddy High residual. |
| **U-F — Modeling, engineering and twins** | Data-model/PyPI/product maintainer | PARTIAL | Gate 36 FQ CLOSED; W4: EQ-VOCAB + ECM-ADAPT + DM-10 narrow CLOSED; Soft-OPEN DM-09 scale / EQ-PERSIST / ECM REST / MT breadth. |
| **U-G — Qualified release and handoff** | Release maintainer + operator | RELEASED (hub FQ) | OPS PINNED **`sha-7ad6479` / 3.5.43** · stress `20260921T234148Z` (V6). Prior **`sha-1677c33` / 3.5.37**. Soft remainders: UA-02/05/08/09, UA-10 S5 residual, U-H Nessus. |
| **U-H — Licensed Nessus assessment** | Operator/customer security | BLOCKED — licensed scanner and isolated assessment host | Actual external and credentialed assessment of representative standalone/field hosts, verified scan completeness and policy, remediations and retest. Never substitute Python/ZAP/Trivy or synthetic XML for this result. |

## Wave U remainder cycles (V1–V8) — SUPERSEDED 2026-09-22

**SUPERSEDED** by post-FQ master [`.cursor/plans/wave_u_post-fq_remainder.plan.md`](.cursor/plans/wave_u_post-fq_remainder.plan.md) (W-UI → W0–W7). Historical V1–V8 rows below are closed for product landing; residual Soft-OPEN continues under W1–W7 / ECM plan.

| Cycle | Scope | Status | Soft-OPEN / UA | Subplan |
| --- | --- | --- | --- | --- |
| **V1** | Tip Trivy + product HTTPS candidate soak | **LANDED** (nginx≥1.28.3 in Dockerfile; soak residual → W1) | UA-02/05 residual tip rescan | [wave_u_v1_images_https.plan.md](.cursor/plans/wave_u_v1_images_https.plan.md) |
| **V2** | Product MQTT ACL + disposable ZAP AF | **LANDED** (MQTT ACL); ZAP AF execute → W2 | UA-04 residual | [wave_u_v2_mqtt_zap.plan.md](.cursor/plans/wave_u_v2_mqtt_zap.plan.md) |
| **V3** | MT breadth batch + field/host live evidence | **LANDED** (+6 routes); residual PLANNED → W2 | `sec-harness-mt-breadth` residual | [wave_u_v3_mt_field_host.plan.md](.cursor/plans/wave_u_v3_mt_field_host.plan.md) |
| **V4** | PyPI `open-fdd` **4.4.3** publish | **CLOSED** (PyPI live 4.4.3) | — | [wave_u_v4_pypi_publish.plan.md](.cursor/plans/wave_u_v4_pypi_publish.plan.md) |
| **V5** | S5 DM-07..10 / EQ-VOCAB / ECM-ADAPT / Pages | **PARTIAL→advanced (W4)** · EQ-VOCAB + ECM-ADAPT + DM-10 narrow PASS; DM-09/PERF-1 scale Soft-OPEN | EQ-PERSIST · PERF scale · ECM REST | [wave_u_v5_s5_dm_ecm.plan.md](.cursor/plans/wave_u_v5_s5_dm_ecm.plan.md) |
| **V6** | Single final MEGA FQ + OPS PINNED bump | **CLOSED FQ** | OPS PINNED `sha-7ad6479` / 3.5.43 | [wave_u_v6_final_mega.plan.md](.cursor/plans/wave_u_v6_final_mega.plan.md) |
| **V7** | Tenant path migrate `tenants/{tid}/…` | **LANDED** (dual-read); live APPLY → W5 | live APPLY residual | [wave_u_v7_tenant_path_migrate.plan.md](.cursor/plans/wave_u_v7_tenant_path_migrate.plan.md) |
| **V8** | Historian H4 + runtime compaction | **LANDED** (product); live compact soak → W5 | live soak residual | [wave_u_v8_historian_compaction.plan.md](.cursor/plans/wave_u_v8_historian_compaction.plan.md) |

**Follow-on tip:** W-UI quiet SPA **3.5.44** (#980) landed. Next: W0 hygiene (this docs tip) → W1 tip rescan → … → W7 MEGA.

**Deferred:** `stage-c-idp-mfa-sku` · U-H Nessus · `local-bacnet-ot-bench`.

Rules: smoke-only between cycles; **one MEGA at W7** (post-FQ plan); log FAIL in BUG_REPORT before fix.

These owner labels are responsibilities, not assigned GitHub usernames. Name the actual owner when scheduling the milestone. Set due dates when capacity and external dependencies are known; do not invent dates to create apparent commitment.

## Evidence record required before verification

For each milestone append or link a record with:

| Field | Required value |
| --- | --- |
| Candidate | Full source SHA, release version, per-component digest and platform |
| Test identity | Harness SHA, profile, fixture/config hashes, tool and vulnerability DB versions |
| Execution | CI/run IDs, timestamps, artifact references and hashes, measured pass/fail/blocked counts |
| Coverage | Required controls/gates, approved N/A applicability and replacement evidence |
| Findings | Linked bug IDs, remediation PR/commit, retest result; owner/rationale/expiry for accepted Medium findings |
| Acceptance | Reviewer, decision, date, explicit remaining limitations |
| Release | Published/deployed pin, verification after deployment, backup/rollback reference and handoff |

Keep credentials, private targets and raw security artifacts out of this index. Store private evidence according to [SECURITY.md](SECURITY.md); public documentation can contain secure setup, synthetic examples and aggregate status.

## Working with GitHub milestones

1. Create a GitHub milestone for the outcome above when its work is scheduled; use the same ID/name and link this file.
2. Attach the relevant implementation and regression-test PRs. Multiple small PRs may contribute to one milestone.
3. Track acceptance in an aggregate issue/checklist containing only non-sensitive criteria. Use private security reporting for unresolved vulnerability details.
4. Before closing, reconcile all child work and independent exit evidence. A GitHub completion percentage counts closed items; it does not establish test coverage or security.
5. Record the verification/release decision here and in BUG_REPORT, then close the remote milestone. Reopen when new evidence invalidates acceptance.

No remote milestones were created by the 2026-09-20 audit. This file is ready to guide that setup.

## AFDD-996 — resource controls and recovery qualification — CLOSED (accepted envelope)

GitHub milestone: [AFDD-996](https://github.com/bbartling/open-fdd/milestone/3) · acceptance issue: [#996](https://github.com/bbartling/open-fdd/issues/996) (**closed 2026-09-24**).

### Verification (accepted)

| Item | Evidence |
| --- | --- |
| Candidate | #995 · hub health `3.5.51+69140983c783` / `sha-6914098` |
| Compact ACME hive | APPLY `reports/wave_u_acme_compaction_apply_20260923T125014Z/` — eligible parts **54814 → 0**; flush coalesce `OPENFDD_PARQUET_FLUSH_SECONDS=300` |
| Bounded queries | Tip seatbelts (lookback / wall timeouts / fail-closed) + `OPENFDD_QUERY_MEMORY_MB=512` honored via bounded DataFusion sessions |
| Operator outcome | Railway hub analytics/ingest **smooth and fast** after compact hive — maintainer-accepted operating envelope |

### Decision path

**Keep web + central + MQTT** on the existing topology. Compact Parquet hive + bounded DataFusion queries are sufficient for the accepted ACME/Railway workload. No Pro plan upgrade, dedicated analytics worker, or Timescale/DB migration required to close this issue.

### Release note

This closes the **resource / crash-recovery acceptance** for the compact-hive envelope. It does **not** claim unlimited scale, continuous-AFDD timer FQ, or a full MEGA `fully_qualified=true` re-pin. Soft residuals (aggregate process-wide admission, AFDD fail-closed contracts, flush loss bounds, timer soak) may open as follow-up tips without reopening #996 unless the compact-hive envelope regresses.

### Historical notes (superseded by closeout)

- Exhaustion run: [`reports/issue996_exhaustion_20260923/SUMMARY.md`](reports/issue996_exhaustion_20260923/SUMMARY.md) — disposable findings informed tip seatbelts; not a remaining blocker for this accepted path.
- Bounded smoke: [`reports/issue996_codex_20260923/SUMMARY.md`](reports/issue996_codex_20260923/SUMMARY.md).


## 2026-09-23 — Issue #996 — candidate verification (historical)

Published #995 candidate `sha-6914098` (3.5.51) deployed to Railway central/MQTT/web after verified backup and green publish checks. Daily AFDD remained **bulk/off** during early smoke. Selected analytics + concurrent manual AFDD smoke passed. **Superseded 2026-09-24** by maintainer closeout: compact hive + bounded queries accepted; see AFDD-996 CLOSED above.


## 2026-09-30 — tip 3.5.59 / sha-97ca09d field stress (not FQ)

| Item | Evidence |
| --- | --- |
| Tip | VERSION **3.5.59** · commit `97ca09d0c1ca` · GHCR `sha-97ca09d` |
| Merged this cycle | #1076 docs cookbook sidebar · #1079 wave I/K ACME retarget (#1069 product) · #1081 tip bump |
| Parked (do not merge) | Codex drafts **#1075** · **#1067** · draft **#1080** |
| Railway hub | health `3.5.59+97ca09d0c1ca` · edges=2 · ingest_reject=0 · no Railway backup this cycle |
| Field | fieldbus `pi-1` ACME `has_telemetry=true`; `vim-1` `has_telemetry=false` |
| ART | `reports/nightly-ot-bench_20260930T221540Z/` · **FAIL** · `fully_qualified=false` |
| Soft-OPEN leave open | **#1069** Wave I `bas_vs_web_acme` oa_t/web_oa_t absent (`product_fail=0`, `field_catalog_soft_open=1`); Wave K `mqtt_zone_and_oa` oa_t absent |
| Gate39 leave open | **#1070** `39_mqtts_gap_blame` **BLOCKED** `instrumentation_complete=false` rows=[] snapshot-only |
| GH tidy | squash-merged #1076/#1079/#1081; head branches deleted; only parked drafts remain open |

Do **not** claim FQ or OPS pin from this run. Close Soft-OPEN only after tip+field unique prove clears Soft-OPEN + full stress notes.

## Draft — #1034–#1070 closeout checklist (2026-10-01)

This list is for Ben. It does **not** close any GitHub issue. A merged PR is not acceptance. Do not mark `fully_qualified` or move the OPS pin from this note.

| Issue | GitHub | Where the work stands | Still required before close |
| --- | --- | --- | --- |
| #1034 | OPEN | Schedule code landed with #1054. Issue still open. | Tip+field proof of the wall-clock cadence. Not re-litigated here. |
| #1035 | OPEN | Lookback upsert landed with #1054. Issue still open. | Same tip+field proof. `update_all` stays rejected. |
| #1036 | PR merged | Stress RAM / ACME lookback note. Not an open product issue. | — |
| #1037 | OPEN | RCx `equipment_id` LIKE. Not in this change. | Type/role selection, then tip proof. |
| #1038 | OPEN | Mechanical-cooling id LIKE. Not in this change. | Type/role selection, then tip proof. |
| #1039 | OPEN | Related merge #1060. Issue still open. | Confirm the tip no longer picks weather by id text, then field proof. |
| #1040 | OPEN | OAT-METEO `AHU%` LIKE. Not in this change. | Type/role SQL, then tip proof. |
| #1041 | OPEN | Analytics labels inferred from id text. Not in this change. | Stamp/role labels, then tip proof. |
| #1042 | OPEN | Related merge #1060. Issue still open. | Overview / plant-health / applicability proof on tip. |
| #1043 | CLOSED | Epic. | — |
| #1044 | OPEN | Parquet cache + session unload are in tree (#1056). Gate 42 classifies cache hit (`elapsed_ms`, no silent stale) and `historian_resident` clear on leave. | Tip+field: cache-hit latency and RSS after CSV unload. Do not close on the classifier. |
| #1045 | OPEN | Related merge #1059. Issue still open. | PyPI/WattLab stamp proof. |
| #1046 | OPEN | Related merge #1059. Issue still open. | Pandas cohort proof. |
| #1047 | OPEN | Related merge #1058. Issue still open. | Agent-spec proof that id heuristics are not the fallback. |
| #1048 | CLOSED | Local fieldbus ingest. | — |
| #1049 | OPEN | 100 GiB oldest-first + preflight are in tree (#1056). Gate 42 runs `openfdd_disk_preflight.py --self-test`. Railway eviction stays off unless enabled. | Real edge disk: live cap, prune, update with and without headroom. |
| #1050 | OPEN | SPA preview is newest-N, default 10, options 10/20/50/100/500 (#1052). Gate 42 checks that contract. | Tip field check on a package or ACME plot. |
| #1051 | PR merged | Gap-blame scorecard. | See #1070. |
| #1052 | PR merged | Series preview. | See #1050. |
| #1053 | CLOSED | VAV/zone RCx gate. | — |
| #1054 | PR merged | AFDD schedule. | See #1034 / #1035. |
| #1055 | PR merged | VAV occupied comfort. | — |
| #1056 | PR merged | Cache + disk budget. | See #1044 / #1049. |
| #1057–#1062 | PRs merged | Id-heuristic and fieldbus follow-ons. | Matching open issues above stay open until tip proof. |
| #1063 | OPEN | Web `/api/health`, `/api/version`, `/api/auth/status`, and `/api/auth/login` fail fast to JSON 503. SPA aborts those calls and keeps the shell up. Gate 42 blackhole-checks that contract. | Railway re-pin of this web+central, then a demo path with no multi-minute API blackout, plus central memory notes. |
| #1064 | CLOSED | Tenant-from-scope ingest. | — |
| #1065 | PR merged | Historian scope fix. | — |
| #1066 | PR merged | Frontend dependency bump. | — |
| #1067 | OPEN | Codex docs draft. **Left alone.** | Do not merge from this cycle. |
| #1068 | CLOSED | Gate 17 chiller health fields. | — |
| #1069 | OPEN | Wave I/K now split `oa_t` and `web_oa_t` (and Wave K `zone_t` vs `oa_t`). Absent column = field-catalog Soft-OPEN and still fails the gate. Present column with no values = product FAIL. A zone value is not hidden inside an oa_t Soft-OPEN. | Tip+field: product_fail=0 only when the columns that exist have values; Soft-OPEN clears only when the missing AV columns are actually in the catalog. Not a product PASS. |
| #1070 | OPEN | Gate 39 `probes` names the publish-ledger read. Truncated equipment ids are INCONCLUSIVE, not EDGE. `rows=[]` stays `instrumentation_complete=false` (exit 2 BLOCKED). | OptiPlex `OPENFDD_EDGE_BASE` plus hub inventory so the scorecard has rows. Trailing window still needs non-empty RTU and VAV series. Do not close on an empty snapshot. |

Parked historically in the 2026-10-01 note: older Codex drafts. **2026-10-03 mega train:** Cursor **takes over** security draft [#1102](https://github.com/bbartling/open-fdd/pull/1102) / #999 (not left alone). See **Mega patch train** section above.
