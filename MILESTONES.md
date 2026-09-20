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
| **U-A — Evaluated qualification** | Security/test maintainer | IN PROGRESS (3.5.36 tip / #962) | Permanent negatives for 14 audit false-passes; both gate 36 required; railway_field candidate/artifact validation; tenant_ids membership; MQTT require-live; ZAP fail-closed; Nessus per-host completeness. CI + MEGA still required for VERIFIED. |
| **U-B — Standalone OT readiness** | Deployment/security maintainer | REOPENED / PARTIAL code | HTTPS compose contract + exposure lint on tip; peer candidate soak and trusted TLS still required. |
| **U-C — Field gateway readiness** | Field/MQTT maintainer | REOPENED / PARTIAL code | Field-only exposure + edge compose lint; provisioner key `0600` + dual-tenant isolation tests; MQTT entrypoint fail-closed. Live runtime delivery/host probe still required. |
| **U-D — Web application assurance** | App/security maintainer | REOPENED | Auth/tenant/role matrix and browser regressions; authenticated ZAP candidate coverage and reviewed findings; private artifacts; bounded pre/post-stress checks; documented exploratory-review remainder. |
| **U-E — Image and host acceptance** | Release/deployment maintainer | REOPENED / PARTIAL | Web Alpine base bump + disposition table; Debian unfixed tracked; Caddy added to Trivy all-scope. Rescan of published tip digests still required before VERIFIED. |
| **U-F — Modeling, engineering and twins** | Data-model/PyPI/product maintainer | PARTIAL | Remaining Wave S requirements reconciled: DM-06..10 as applicable, tenant-safe graph/JSON/SPARQL, units and provenance for engineering quantities, ECM tools/docs, published wheel validation, SQL/API oracle and model/ECM gates. |
| **U-G — Qualified release and handoff** | Release maintainer + operator | IN PROGRESS | Required CI and profile acceptance green; exact published images; backup/re-pin; complete final MEGA including both gate 36 checks; independent evidence reconciliation; updated runbook/pins; clean-environment handoff. |
| **U-H — Licensed Nessus assessment** | Operator/customer security | BLOCKED — licensed scanner and isolated assessment host | Actual external and credentialed assessment of representative standalone/field hosts, verified scan completeness and policy, remediations and retest. Never substitute Python/ZAP/Trivy or synthetic XML for this result. |

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
