# Security harness evidence — 3.5.29 (offline / CI)

Candidate tip branch: `tip/3.5.29-security-harness` (PR #948).  
Harness revision: working tree after inventory v2 + MT fail-closed.  
**Live hub execute: NOT RUN** (HOLD). **Layer C Rust: pending GH Actions.**

| Requirement | Implementation | Check / test IDs | Command | Result | Evidence | Limitation / next |
|---|---|---|---|---|---|---|
| Inventory honesty | `inventory/routes.json` v2 | dispositions IMPLEMENTED/PLANNED/BLOCKED_POLICY | `unittest test_inventory_integrity` | PASS | tests/security | Fill TODO schemas per route |
| Dup check IDs | routes.json | fdd-rules alias unique | integrity test | PASS | — | — |
| Implemented registry | `implemented_checks.json` | ~33 suite IDs | integrity test | PASS | — | Expand suites → promote PLANNED |
| CLI dry-run | `openfdd_security_probe.py` | profile isolated_full | `--dry-run` | exit 0 executed=false | reports/security (local) | Never qualifies |
| Layer A/B | `tests/security/*` | detectors listed in README | `unittest discover -s tests/security` | PASS (prior 34+integrity) | — | — |
| Manifest sabotage | `test_orchestrator_sabotage` | dry-run/hash/zero checks | unittest | PASS | — | — |
| Empty membership MT | `tenant.rs` resolve_fail_closed + routes | `empty_membership_operator_denied_under_mt` | CI `preauth_disclosure` | **PENDING CI** | — | Must PASS before merge |
| Scoped admin mint | `auth_agent_token` | `scoped_admin_cannot_mint_foreign_or_blank_agent` | CI | **PENDING CI** | — | Must PASS before merge |
| Jobs/global meta | policy_dispositions.json | SEC-JOB-OWNERSHIP, SEC-GLOBAL-META | — | BLOCKED_POLICY | inventory | Policy decision |
| Gate 25/25b/26 wiring | run_railway_hub_stress.sh | gate IDs | script review | wired | — | Live EXECUTE later |
| ZAP dispositions | zap_risk_dispositions.json | — | default ACCEPT=0 | configured | — | Populate on first Medium |
| Live 25/25b PASS | — | — | hub stress EXECUTE=1 | **NOT RUN** | — | After tip pin |

