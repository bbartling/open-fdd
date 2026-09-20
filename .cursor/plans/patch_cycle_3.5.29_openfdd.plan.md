> **SUPERSEDED by Wave U** — do not play. Active master: [`docs/operations/WAVE_U_MASTER.md`](../../docs/operations/WAVE_U_MASTER.md) · [`.cursor/plans/wave_u_security_hardening_master.plan.md`](wave_u_security_hardening_master.plan.md). Retained as historical/child detail only.

---
name: Open-FDD 3.5.29 patch cycle
overview: "3.5.29 security-harness-ship + audit §§1–7. PR #948 iterating — inventory honesty, layer-C MT fixes, fail-closed qual. Do not merge until requirement-to-evidence table is green for offline/CI layers. Live execute + MEGA stress after tip pin only."
todos:
  - id: p0-hygiene-start
    content: "GH hygiene START"
    status: completed
  - id: plan-reconcile
    content: "Master plan req↔task↔exit for audit §§1–7 + layer C"
    status: in_progress
  - id: inv-honesty
    content: "Inventory v2 PLANNED/IMPLEMENTED; dup IDs fixed; CI integrity"
    status: in_progress
  - id: xyz-suites
    content: "X/Y/Z suite coverage expansion toward planned_check_ids"
    status: pending
  - id: layer-c-rust
    content: "Layer C Rust regressions + fail-closed empty-membership/scoped-mint"
    status: in_progress
  - id: fail-closed-qual
    content: "ZAP dispositions; 25/25b required; dry-run≠PASS; evidence validator"
    status: in_progress
  - id: evidence-table
    content: "Requirement-to-evidence table + docs truth"
    status: pending
  - id: p4-pr-merge
    content: "PR 948 green merge only after offline+CI evidence"
    status: pending
  - id: p5-tip-gate
    content: "GHCR tip complete sha-<7>"
    status: pending
  - id: p6-backup-repin
    content: "Backup + Railway re-pin"
    status: pending
  - id: p7-fieldbus-bacnet
    content: "Fieldbus tip + local BACnet@38400 if picked"
    status: pending
  - id: p8-mega-stress
    content: "MEGA stress with OPENFDD_SECURITY_EXECUTE=1; 25/25b PASS; 26 N/A or PASS"
    status: pending
  - id: p10-bug-report
    content: "BUG_REPORT + hygiene end"
    status: pending
isProject: false
---

# Open-FDD 3.5.29 — security harness (audit-complete)

**PR:** [#948](https://github.com/bbartling/open-fdd/pull/948) `tip/3.5.29-security-harness` — **do not merge** until §§1–5 offline/CI evidence below is green.

**Contracts (mandatory, not satisfied by linking alone):**
- [`.cursor/agents/openfdd-security-python-harness.md`](../agents/openfdd-security-python-harness.md)
- [`.cursor/plans/security_stress_integration_audit.md`](security_stress_integration_audit.md)

**Tip decision:** `security-harness-ship` — Python probe + gates 25/25b/26 + legacy false-PASS repairs + MT fail-closed product fixes (empty membership, scoped admin mint). Soft-OPEN acme-oa-t / local-bacnet follow-on.

**HOLD:** No Railway re-pin / live `OPENFDD_SECURITY_EXECUTE` until tip GHCR pin. Offline + CI layer C first.

---

## Reconciliation (2026-09-18 afternoon)

| Finding from mid-flight review | Status now |
|---|---|
| “No executable harness” | **False after tip commit** — CLI + suites exist; revalidated offline |
| Duplicate `/api/fdd/rules` vs `/api/fdd-rules` check IDs | **Fixed** — unique `*_alias` IDs |
| 107 routes labeled COVERED without tests | **Fixed** — inventory v2: **IMPLEMENTED 6 / PLANNED 101 / BLOCKED_POLICY 31** |
| Missing schema/fixture/side-effect fields | **Stubbed** on all routes (`TODO` schemas until filled per route) |
| Layer C Rust missing | **In progress** — fail-closed resolve + scoped mint + regression tests added |
| `ACCEPT_ZAP_MEDIUM=1` blanket | **Default now 0** + `zap_risk_dispositions.json` |

Honest coverage: suite emits **~33** check IDs; only **6** routes intersect as IMPLEMENTED. Remaining PLANNED routes are **not** tested — do not claim otherwise.

---

## Requirement → task → exit (must all pass before merge)

### §1 Inventory

| Req | Task | Exit |
|---|---|---|
| Unique check IDs | `inv-honesty` | `inventory_integrity_errors()==[]` |
| PLANNED ≠ IMPLEMENTED ≠ COVERED | `inv-honesty` | disposition counts; no COVERED |
| Schema/selectors/side_effects/fixtures | `inv-honesty` | fields present (TODO schemas OK temporarily) |
| CI drift + dup detection | `test_inventory_integrity.py` | unittest PASS |
| Nested routers inventoried | `find_uninventoried_routes` empty vs `routes.rs` | PASS |

### §2 Python tools

| Req | Task | Exit |
|---|---|---|
| Lib/CLI/config/schemas/README | shipped under `scripts/security/` | dry-run exit 0, `executed=false` |
| Profiles + budgets + redaction | suites + transport | broken-fixture detectors PASS/FAIL correctly |
| Unknown suite / subset ≠ full profile | config tests | FAIL closed |

### §3 X/Y/Z + product concerns

| Req | Task | Exit |
|---|---|---|
| Core X/Y/Z on fixtures | suites | healthy 31/31; detectors FAIL on faults |
| Empty-membership MT | `layer-c-rust` | `empty_membership_operator_denied_under_mt` PASS in CI |
| Scoped-admin mint | `layer-c-rust` | `scoped_admin_cannot_mint_foreign_or_blank_agent` PASS in CI |
| Jobs/global-meta ownership | BLOCKED_POLICY until policy decision | disposition BLOCKED_POLICY + finding IDs |
| Browser login/logout | Playwright existing / follow-on | named separate; Python does not claim browser |

### §4 Evaluate A/B/C

| Layer | Exit |
|---|---|
| A offline unit | `unittest discover -s tests/security` PASS |
| B broken fixtures | detector map in README/evidence table |
| C Rust CI | `preauth_disclosure` new tests PASS on GH Actions (no local cargo) |

### §5 Legacy + runners

| Req | Exit |
|---|---|
| Gates 25/25b wired required | in `run_railway_hub_stress.sh` |
| Gate 26 | N/A when `OPENFDD_SECURITY_MQTT_ACL!=1` (not BLOCKED) |
| 401≠ACL; Wave L N/A; unique ART dirs | repaired scripts |
| Dry-run gate 25 | BLOCKED (honest) until EXECUTE |

### §6 Fail closed

| Req | Exit |
|---|---|
| Structured verdict + hashes | sabotage tests |
| Required 25/25b cannot waive missing creds | BLOCKED ⇒ not FQ |
| 26 required + BLOCKED ⇒ not FQ; N/A when out of profile | gate script |
| live_readonly ≠ isolated_full | profile registry |
| all-N/A security ≠ PASS | manifest tests |
| ZAP rule dispositions | default ACCEPT_ZAP_MEDIUM=0 |

### §7 Evidence + tip cycle

| Phase | When |
|---|---|
| Offline/CI evidence table | before merge |
| Merge #948 → GHCR | after CI green including Rust layer C |
| Backup + re-pin + fieldbus | after tip complete |
| MEGA stress + EXECUTE=1 | last |
| BUG_REPORT / hygiene | closeout |

---

## Commands (offline — run every push)

```bash
python3 -B -m unittest discover -s tests/security -v
python3 -B -m unittest discover -s tests/qualification -v
python3 scripts/qualification/zap_baseline_verdict.py --selftest
# Layer C: CI only on bensbench — cargo test -p openfdd-central --test preauth_disclosure
```

## Anti-patterns

- Marking PLANNED routes as tested
- Merging #948 before layer-C CI green
- Live stress without EXECUTE while claiming security PASS
- Blanket ACCEPT_ZAP_MEDIUM=1 without dispositions
- Cancelling required security work to close the plan
