# R6 adapter gaps — Soft-OPEN tracking (3.6.7)

Soft-OPEN ≠ FQ. Smoke 77/77 ≠ equation proof. Target ≥12 gaps addressed over the train.

| # | Gap | Soft-OPEN disposition (3.6.7) |
| --- | --- | --- |
| 1 | Exact `equipment_id` miss fell back to all sample equipment | **Fixed** — no broaden; return empty/ineligible |
| 2 | Session `params[rule_id]` ignored in SQL render | **Fixed** — passed into `effective_param_strings` |
| 3 | Metric rules wrapped as `fault_hours` only | **Fixed** — metric wrap selects `*` / named cols |
| 4 | Metric outputs labeled FAULT/PASS | **Fixed** — `METRIC` status for non-fault output kinds |
| 5 | Partial ERROR still counted `rules_succeeded` | **Fixed** — any ERROR ⇒ failed (partial ≠ clean success) |
| 6 | Window start/end ignored on history fill | **Soft-OPEN** — honor payload `start`/`end` half-open |
| 7 | Cadence hard-coded 300 | **Soft-OPEN** — `poll_seconds` from payload/params; default 300 |
| 8 | Required-role eligibility incomplete | **Soft-OPEN** — `SKIP_MISSING_ROLES` when required cols all-null |
| 9 | Type applicability bypass edge cases | **Soft-OPEN** — type-first; exact id only when stamp missing |
| 10 | No real `fault_series` / confirm detail publish | **Soft-OPEN** — confirm aggregate `fault_series` object |
| 11 | Weather/utility/CHW role relations incomplete | **Soft-OPEN** — stamped weather/CHW keys join into history |
| 12 | Strict pandas/golden harness | **Soft-OPEN** — `scripts/softopen_r6_harness_check.sh` (smoke + pack pin) |

BPS ↔ OSS: equations stay in hash-pinned SQL pack — adapters bind only.
