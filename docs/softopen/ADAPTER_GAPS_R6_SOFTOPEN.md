# R6 adapter gaps — Soft-OPEN tracking (3.6.6)

Soft-OPEN ≠ FQ. Smoke 77/77 ≠ equation proof. Target ≥12 gaps addressed over the train.

| # | Gap | Soft-OPEN disposition (3.6.6) |
| --- | --- | --- |
| 1 | Exact `equipment_id` miss fell back to all sample equipment | **Fixed** — no broaden; return empty/ineligible |
| 2 | Session `params[rule_id]` ignored in SQL render | **Fixed** — passed into `effective_param_strings` |
| 3 | Metric rules wrapped as `fault_hours` only | **Fixed** — metric wrap selects `*` / named cols |
| 4 | Metric outputs labeled FAULT/PASS | **Fixed** — `METRIC` status for non-fault output kinds |
| 5 | Partial ERROR still counted `rules_succeeded` | **Fixed** — any ERROR ⇒ failed (partial ≠ clean success) |
| 6 | Window start/end ignored on history fill | **Soft-OPEN** — honor payload `start`/`end` half-open |
| 7 | Cadence hard-coded 300 | Open (registry poll Soft-OPEN later) |
| 8 | Required-role eligibility incomplete | Open |
| 9 | Type applicability bypass edge cases | Open (exact-id-after-filter kept) |
| 10 | No real `fault_series` / confirm detail publish | Open |
| 11 | Weather/utility/CHW role relations incomplete | Open |
| 12 | Strict pandas/golden harness | Open (smoke preserved) |

BPS ↔ OSS: equations stay in hash-pinned SQL pack — adapters bind only.
