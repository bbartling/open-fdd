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

## Wave U outcomes — acceptance snapshot 2026-09-20

The independent audit reopened acceptance checks. Statuses below do not erase earlier test runs or imply that existing improvements were absent. The snapshot covered #959/#960 merged and #961 in flight; consult GitHub and BUG_REPORT for later changes.

| ID / suggested GitHub milestone | Scope and owner | Status | Exit criteria |
| --- | --- | --- | --- |
| **U-A — Evaluated qualification** | Security/test maintainer | VERIFIED (evaluator contract on tip) | Permanent negatives + required gate 36s; MEGA `20260921T021332Z` `fully_qualified=true` on `sha-1677c33`. Standalone peer/image remediations remain under U-B/U-E. |
| **U-B — Standalone OT readiness** | Deployment/security maintainer | PARTIAL | HTTPS compose hide web:3000 + trusted-CA peer soak `20260921T023714Z`. Product-image candidate soak still required. |
| **U-C — Field gateway readiness** | Field/MQTT maintainer | PARTIAL | Field-only exposure + key modes + dual-tenant tests; BACnet CI RO key staging fixed in 3.5.38. Product MQTT image ACL Soft-OPEN. |
| **U-D — Web application assurance** | App/security maintainer | PARTIAL | Auth/tenant matrix on MEGA; authenticated ZAP candidate AF still Soft-OPEN. |
| **U-E — Image and host acceptance** | Release/deployment maintainer | PARTIAL | Tip rescan `sha-1677c33`; mqtt 0 H/C; web nginx force-upgrade in 3.5.38; Debian TRACKED UNFIXED; caddy High residual. |
| **U-F — Modeling, engineering and twins** | Data-model/PyPI/product maintainer | PARTIAL | Gate 36 FQ CLOSED on hub tip; Soft-OPEN: DM-07..10, PyPI 4.4.3 publish, MT breadth. |
| **U-G — Qualified release and handoff** | Release maintainer + operator | RELEASED (hub FQ) | OPS PINNED **`sha-1677c33` / 3.5.37** · stress `20260921T021332Z`. Follow-on tip **3.5.38** (BACnet CI keys + nginx/trivy/HTTPS trust) not yet OPS-repinned. Soft remainders: UA-02 product soak, UA-05 Debian/caddy, UA-10 S3/S5, U-H Nessus. |
| **U-H — Licensed Nessus assessment** | Operator/customer security | BLOCKED — licensed scanner and isolated assessment host | Actual external and credentialed assessment of representative standalone/field hosts, verified scan completeness and policy, remediations and retest. Never substitute Python/ZAP/Trivy or synthetic XML for this result. |

## Wave U remainder cycles (V1–V8) — 2026-09-21

Execution master: [`.cursor/plans/wave_u_remainder_patch_cycles.plan.md`](.cursor/plans/wave_u_remainder_patch_cycles.plan.md). Hub FQ on **3.5.37** remains RELEASED; these cycles close Soft-OPEN / PARTIAL acceptance without cancelling U-H or Stage C IdP.

| Cycle | Scope | Status | Soft-OPEN / UA | Subplan |
| --- | --- | --- | --- | --- |
| **V1** | Tip Trivy + product HTTPS candidate soak | **IN FLIGHT** (3.5.39 nginx + candidate probe) | UA-02, UA-05 | [wave_u_v1_images_https.plan.md](.cursor/plans/wave_u_v1_images_https.plan.md) |
| **V2** | Product MQTT ACL + disposable ZAP AF | **IN FLIGHT** | UA-03, UA-04 | [wave_u_v2_mqtt_zap.plan.md](.cursor/plans/wave_u_v2_mqtt_zap.plan.md) |
| **V3** | MT breadth batch + field/host live evidence | PLANNED | UA-07/08, `sec-harness-mt-breadth` | [wave_u_v3_mt_field_host.plan.md](.cursor/plans/wave_u_v3_mt_field_host.plan.md) |
| **V4** | PyPI `open-fdd` **4.4.3** publish | PLANNED | `wave-s3-pypi-mv-oracle` | [wave_u_v4_pypi_publish.plan.md](.cursor/plans/wave_u_v4_pypi_publish.plan.md) |
| **V5** | S5 DM-07..10 / EQ-VOCAB / ECM-ADAPT / Pages | PLANNED | `wave-s5-dm-remainder` | [wave_u_v5_s5_dm_ecm.plan.md](.cursor/plans/wave_u_v5_s5_dm_ecm.plan.md) |
| **V6** | Single final MEGA FQ + OPS PINNED bump | PLANNED | U-G re-pin after V1–V5 tip | [wave_u_v6_final_mega.plan.md](.cursor/plans/wave_u_v6_final_mega.plan.md) |
| **V7** | Tenant path migrate `tenants/{tid}/…` | PLANNED | `wave-o1-tenant-path-migrate` | [wave_u_v7_tenant_path_migrate.plan.md](.cursor/plans/wave_u_v7_tenant_path_migrate.plan.md) |
| **V8** | Historian H4 + runtime compaction coordinator | PLANNED | `historian-n-building-scale` | [wave_u_v8_historian_compaction.plan.md](.cursor/plans/wave_u_v8_historian_compaction.plan.md) |

**Deferred outside V1–V8:** `stage-c-idp-mfa-sku` (commercial) · U-H Nessus · `local-bacnet-ot-bench` · #958 HOLD baud docs.

Rules: smoke-only between cycles; **one MEGA at V6** (do not wait for V7/V8); log FAIL in BUG_REPORT before fix.

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
