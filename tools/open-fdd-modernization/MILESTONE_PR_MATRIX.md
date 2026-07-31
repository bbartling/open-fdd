# Milestone and PR Matrix

## Purpose

Provide the execution index for the detailed phase documents. PR IDs describe
logical units; split any row further when repository reality makes it too broad.
Do not merge rows merely to reduce PR count.

## Dependency flow

```text
P1-M0 architecture/inventory
  -> P1-M1 fixtures/reference
  -> P1-M2 contracts/platform
  -> P1-M3 parity shell
  -> P1-M4 first full vertical slice
  -> P1-M5 remaining domain slices
  -> P1-M6 independent qualification
  -> P2-M0 control plane
  -> P2-M1 computation closure
  -> P2-M2 shadow/soak
  -> P2-M3 canary
  -> P2-M4 default + observation
  -> P2-M5 deletion
  -> P2-M6 closeout
```

Parallel work is safe only when contracts and files do not overlap. React shell,
fixture catalog, and Rust contract conventions may overlap after P1-M0, but the
first vertical slice must integrate their approved versions.

## Phase 1 matrix

| PR | Outcome | Principal paths | Required evidence | Depends on |
| --- | --- | --- | --- | --- |
| P1-M0-01 | React/Rust modernization ADR and instruction reconciliation | root/service `AGENTS.md`, architecture/web docs, retired frontend note | docs/policy tests; safety review | none |
| P1-M0-02 | Capability, Python exit, API, decision, parity, and session ledgers | `docs/migration/react-rust/` | 100% discovered entry-point coverage | M0-01 |
| P1-M1-01 | Deterministic fixture catalog | test fixtures/generators | hashes, schema, happy/error/boundary coverage | M0 |
| P1-M1-02 | Normalized frozen Python oracle export | oracle-only test tooling | three byte-stable normalized runs | M1-01 |
| P1-M1-03 | Streamlit interaction and screenshot baseline | UI e2e/reference evidence | scenario manifests, desktop/narrow/error states | M1-01 |
| P1-M2-01 | Cross-route Rust contract conventions | contracts/central/types | compatibility and error/auth/state tests | M0 |
| P1-M2-02 | Strict React project and delivery shell | new frontend/web build | lint/type/unit/build/container smoke | M0-01, M2-01 |
| P1-M2-03 | Async operations substrate | central/domain/client | state machine, cancellation, restart | M2-01 |
| P1-M3-01 | Streamlit-like frame/tokens | React/CSS | geometry and controlled visual diffs | M1-03, M2-02 |
| P1-M3-02 | Accessible parity widget primitives | React components | component/keyboard/a11y/visual states | M3-01 |
| P1-M3-03 | Routing and explicit session-state translation | React router/query/state | refresh/back/deep-link tests | M2, M3-02 |
| P1-M4-01 | React durable Jobs | React + central jobs client | CRUD/revision/reload/browser tests | M2, M3 |
| P1-M4-02 | Rust safe upload/package ingest | central/edge/contracts | hostile ZIP, cleanup, memory/integration | M1, M2 |
| P1-M4-03 | Mapping/validation UI and Rust contract | React/Rust/fdd_core | missing/ambiguous roles, revision, parity | M4-01/02 |
| P1-M4-04 | SQL FDD run/results/download | React/Rust/fdd_rules/sql | end-to-end no-Python workflow | M4-03 |
| P1-M5-A* | Rule catalog/tuning families | registry/central/React | metadata/default/bounds/injection | M4 |
| P1-M5-B* | FDD and RCx dataset/plot families | SQL/central/React | semantic chart + performance | M4 |
| P1-M5-C* | Analytics/metering families | SQL/Rust/React | numeric/temporal oracle parity | M1, M4 |
| P1-M5-D* | Findings/dispositions | central/React | correlation/revision/audit | M4 |
| P1-M5-E* | Reports/artifacts/WattLab | Rust/React/contracts | semantic artifact/consumer compatibility | M4 |
| P1-M6-01 | Python exit matrix closure | ledgers/policy tests | no BLOCKED rows | all P1 features |
| P1-M6-02 | Independent no-Python React/Rust stack | containers/compose/release | clean topology, health, SBOM | M6-01 |
| P1-M6-03 | Phase 1 release-candidate qualification | evidence/docs | complete test/parity/rollback record | M6-02 |

`*` means repeat as small domain-family PRs. A family is typically one related
rule group, plot dataset, metric group, artifact type, or findings workflow—not
the entire M5 category.

## Phase 2 matrix

| PR | Outcome | Principal paths | Required evidence | Depends on |
| --- | --- | --- | --- | --- |
| P2-M0-01 | Reversible sticky cohort routing | config/router/web | route tests and rollback drill | Phase 1 exit |
| P2-M0-02 | Migration telemetry/dashboards/alerts | central/web/ops | forced-failure alert evidence | M0-01 |
| P2-M0-03 | Expand/contract rollback compatibility | contracts/jobs/storage | old/new read and backup/restore | M0-01 |
| P2-M1-[family]-01 | Rule/analytics metadata contract | registry/contracts | integrity/schema tests | P1 evidence |
| P2-M1-[family]-02 | DataFusion SQL/Rust replacement | SQL/Rust | unit/boundary/plan/performance | family-01 |
| P2-M1-[family]-03 | Oracle parity proof | bench/evidence | denominators/deltas/classifications | family-02 |
| P2-M1-[family]-04 | Production caller cutover | central/React | no-Python tracing/policy + integration | family-03 |
| P2-M1-[family]-05 | Twin deletion after window | Python/deps/docs | call-site/full regression/image scan | family-04 + window |
| P2-M2-01 | Non-writing shadow comparator | comparison/evidence | immutable replay and classified deltas | computation closure |
| P2-M2-02 | Restart/concurrency/large-data soak | ops/tests | budget and recovery record | M2-01 |
| P2-M3-[stage] | Canary stage/promotion record | routing/ops | thresholds, samples, exact digest | M0, M2 |
| P2-M4-01 | React default route | configuration/docs | pre/post/rollback smoke | 100% canary approval |
| P2-M4-02 | Fallback observation closeout | evidence/docs | fallback reasons and healthy window | M4-01 |
| P2-M5-01 | Delete leaf Python production twins | Python/Rust wiring | call-site/full regression/no-Python | M4-02 |
| P2-M5-02 | Delete Streamlit product | `services/ui`, image/scripts | browser/container/upgrade/SBOM | M5-01 |
| P2-M5-03 | Apply root oracle/package decision | `open_fdd`, packaging | explicit human decision + consumer tests | M5-02 |
| P2-M5-04 | CI/compose/release/docs cleanup | workflows/containers/docs | clean deployment and link/policy scans | M5-02/03 |
| P2-M6-01 | Final no-Python qualification | all/evidence | immutable clean-host and upgrade matrix | all P2 |
| P2-M6-02 | Program closeout | ledgers/docs/releases | final matrices, risks, recovery ref | M6-01 |

## PR size and merge rules

Prefer a PR that a reviewer can understand in one sitting:

- roughly one contract family or one user scenario;
- independently testable;
- no unrelated dependency updates;
- no hidden generated bulk;
- migration ledgers included;
- rollback or non-deployment statement included.

Lines changed are not the primary size metric. A generated TypeScript client can
be large while the decision is small; a ten-line schema change can be
operationally large.

Do not merge when:

- required CI is skipped or not collected;
- an UNKNOWN parity mismatch remains;
- the PR depends on an undocumented manual data edit;
- old and new paths can both write conflicting durable truth;
- a target contract leaks Python/session/filesystem implementation;
- a moving image tag is the only evidence;
- matrices claim a later status than evidence supports.

## Suggested labels

```text
phase-1
phase-2
react-parity
rust-api
datafusion-sql
contract
python-exit
cutover
deletion
security
performance
needs-domain-review
needs-ux-review
blocked-external
```

## Milestone promotion record

For each milestone, append:

```markdown
## [MILESTONE] promotion

- decision: PASS | CONDITIONAL | FAIL
- source commit:
- PRs:
- immutable image digests:
- required tests:
- actual pass/fail/skip:
- parity evidence:
- security/performance evidence:
- rollback result:
- open waivers and expiry:
- blockers:
- reviewers:
- next milestone authorized:
```

CONDITIONAL does not authorize deletion or production promotion when the
condition concerns correctness, data integrity, security, unknown parity, or
rollback.
