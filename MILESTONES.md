# Open-FDD milestones

This is the release-outcome index. [Wave U master](docs/operations/WAVE_U_MASTER.md) owns the current execution order; [BUG_REPORT_WAVE_P](docs/operations/BUG_REPORT_WAVE_P.md) owns bugs, operational history and evidence. Historical migration milestones remain under `docs/migration/` and `openfdd_agent_spec/`.

## Status rules

- **PLANNED / IN PROGRESS:** requirements or implementation remain.
- **PARTIAL / REOPENED:** useful work exists, but acceptance evidence is incomplete or contradicted.
- **BLOCKED:** name the external dependency, owner and next action; continue independent work.
- **VERIFIED:** all exit criteria passed on the identified candidate/profile with reviewable evidence.
- **RELEASED:** verified candidate published/deployed as applicable, with rollback and handoff recorded.
- **DEFERRED:** explicitly agreed scope/date/owner. Never use cancellation to hide an unmet requirement.

A merged PR, a passing unit suite, a completed scan, and a verified deployment are different achievements. Record them separately. No milestone becomes VERIFIED from an old pin, skipped test, changed threshold or unreviewed exception. Actual licensed Nessus results are separate from readiness work that needs no license.

## Operations protocol workspace Phase 4 — draft / not field-qualified

**Owner path:** draft PR [#1099](https://github.com/bbartling/open-fdd/pull/1099),
branch `feat/protocol-workspace-phase4`, stacked on Phase 3D. The implementation
head currently recorded in the session log is `c779a851`.

### Landed in the draft branch

- Versioned bounded priority-history contract with exact P1–P16 snapshots,
  scope and request correlation, opaque cursor binding, and safe typed errors.
- Edge-local durable history store and opt-in scheduler. It visits one trusted
  configured device after each completed interval (default 3600 seconds,
  minimum 300), has no catch-up burst, and performs no discovery, write,
  release, or remediation action.
- Authenticated fieldbus and central history routes, capability/inventory
  advertisement, OpenAPI declarations, and a React panel that loads history
  only after an explicit user action.
- OT recipes persist `/edge-state`; `central` and `csv` remain cloud-only and
  contain no fieldbus/scanner service. MQTT history synchronization is deferred
  to a separately versioned future transport contract.

### Evidence and remaining acceptance

- Local fieldbus tests, central compile/route tests, frontend contract/UI tests,
  production build, and Compose/topology checks pass on the draft branch.
- Frontend lint still reports pre-existing repository warnings when run with
  `--max-warnings=0`; this is a CI hygiene item, not silently treated as pass.
- GH Actions and Astra review must pass before the PR is mergeable. No GHCR
  refresh, deployment, live BACnet bench test, live Haystack probe, device
  discovery, WriteProperty/release, or FQ/field qualification has happened.
- Bench qualification is a separate gate: verify reachability of the known
  read-only BACnet device 5007 first, halt if unreachable, and discover/verify
  any Haystack endpoint instead of assuming an address. Record evidence and
  rollback details here and in `openfdd_agent_spec/SESSION_LOG.md` before
  changing status to VERIFIED.

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

Parked and not touched: Codex **#1067**, **#1075**, **#1080**.
