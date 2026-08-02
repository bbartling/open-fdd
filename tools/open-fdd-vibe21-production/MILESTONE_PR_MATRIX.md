# Milestone and PR matrix

## PR sizing rules

- One PR proves one bounded capability or infrastructure gate.
- Target 200–800 changed production lines plus tests/docs; split mechanically
  generated schemas/assets from reviewed logic.
- No PR combines contract design, a new runtime, a full UI workflow, and release
  topology unless inseparable.
- Every PR names one milestone ID, capability IDs, fixtures, evidence paths,
  rollback, and remaining gaps.
- Status advances only as far as evidence supports.

## Phase 1 — recovery

| PR | Deliverable | Depends on | Required evidence |
|---|---|---|---|
| P1-M0-A | Capability ledger + validator | baseline inventory | validator unit tests; complete route/workflow inventory |
| P1-M0-B | Agent/docs authority reconciliation | M0-A | docs/link/terminology checks |
| P1-M1-A | Reproducible hardened React image/topology | M0 | image build; header/config tests |
| P1-M1-B | GHCR `openfdd-web` publication and Streamlit image retirement | M1-A | SHA image/digest/SBOM evidence |
| P1-M1-C | Clean-host no-Python smoke | M1-B | browser/API transcripts; image inspection |
| P1-M2-A | ESLint + real-stack Playwright harness | M1-A | lint failure fixture; browser smoke |
| P1-M2-B | Unified error/loading/recovery behavior | M2-A | injected API failure matrix |
| P1-M2-C | Accessibility/responsive shell | M2-A | axe/keyboard/zoom screenshots |
| P1-M3-A | Refreshed Streamlit parity inventory/baselines | M0 | same-viewport captures and state manifest |
| P1-M3-B | Real chart component and plot contract | M2-A, M3-A | visual/interaction/accessibility plot tests |
| P1-M3-C | Auth/shell slice | M2 | real-stack route tests and visual diff |
| P1-M3-D | Jobs/context slice | M3-C | CRUD/concurrency/deep-link tests |
| P1-M3-E | Upload/import slice | M3-D | boundary/security/large-file tests |
| P1-M3-F | Mapping/roles slice | M3-E | mapping revision and parity tests |
| P1-M3-G | FDD rules/run/results slice | M3-F | contract/numeric/browser tests |
| P1-M3-H | Findings/dispositions slice | M3-G | persistence/audit/download tests |
| P1-M3-I | Reports/metering/WattLab retained slice | M3-H | artifact and calculation parity |
| P1-M4-A-* | SQL oracle closure by rule family | M0 | row-mask/duration/boundary differential tests |
| P1-M4-B-* | RCx/metering algorithm closure | M3-G | equations, golden/adversarial fixtures |
| P1-M4-C | Report runtime ownership | M1 | no-Python artifact generation proof |
| P1-M5-A | Independent qualification pack | all above | full acceptance manifest |
| P1-M5-B | Streamlit supported-runtime retirement | M5-A | dependency/image/docs guard |

## Phase 2 — Rust twin foundation

| PR | Deliverable | Depends on | Required evidence |
|---|---|---|---|
| P2-M0-A | Vibe 21 inventory/disposition/hash manifest | P1 gates | inventory validator |
| P2-M0-B | Frozen Flask/joblib conformance pack | M0-A | reproducible fixture generator |
| P2-M1-A | Rust twin/model/scenario/Unity contracts | M0-B | JSON Schema/OpenAPI round-trip fixtures |
| P2-M1-B | Immutable twin/job artifact store | M1-A | atomicity/hash/path/concurrency tests |
| P2-M1-C | Twin APIs | M1-B | auth/site/OpenAPI integration tests |
| P2-M2-A | Offline portable model exporter | M0-B, M1-A | artifact/card/SBOM/conformance bundle |
| P2-M2-B | Rust feature compiler | M2-A | exact differential vectors |
| P2-M2-C | Rust inference runtime | M2-B | output parity, adversarial model tests, benchmarks |
| P2-M2-D | Model lifecycle APIs | M2-C, M1-B | approve/activate/revoke/rollback/audit tests |
| P2-M3-A | Full multi-target farm release | M0 | reproducible external worker/run manifests |
| P2-M3-B | Qualification/domain policy | M3-A, M2-C | grouped metrics, plausibility/OOD tests |
| P2-M4-A | Scenario schema catalog | M1-A | generated React/Unity conformance |
| P2-M4-B | Scenario run lifecycle | M2-D, M4-A | idempotency/cancel/baseline/artifact tests |
| P2-M4-C | React exact scenario preview | M4-B | real-stack browser and numeric tests |

## Phase 3 — React studio

| PR train | Deliverable | Key gate |
|---|---|---|
| P3-M0-* | URL/state/UX architecture | concurrency and navigation proof |
| P3-M1-* | structured inputs and readiness | provenance/security/large upload |
| P3-M2-* | FDD evidence bridge | trace result to raw evidence |
| P3-M3-* | twin/calibration workspace | reproducible metrics/version approval |
| P3-M4-* | scenario laboratory | exact results, stale request cancellation, OOD UI |
| P3-M5-* | deliverables | hash/version/provenance and no hidden Python runtime |

## Phase 4 — Unity WebGL

| PR train | Deliverable | Key gate |
|---|---|---|
| P4-M0-* | artifact schema/threat model | adversarial fixture inventory |
| P4-M1-* | secure archive import/lifecycle | zip/security/atomic activation tests |
| P4-M2-* | same-origin static serving | header/auth/cache/range tests |
| P4-M3-* | React host + bridge | real WebGL Playwright handshake |
| P4-M4-* | external Unity build contract | pinned build manifest + browser smoke |
| P4-M5-* | performance/operations | budgets, telemetry, rollback |

## Phase 5 — live twin

| PR train | Deliverable | Key gate |
|---|---|---|
| P5-M0-* | observation/mapping contract | time/unit/quality golden fixtures |
| P5-M1-* | replay | deterministic seek/reconnect/DST tests |
| P5-M2-* | MQTTS/live subscriptions | mTLS/ACL/backpressure/reconnect tests |
| P5-M3-* | operational overlays | measured/predicted/FDD provenance tests |
| P5-M4-* | actuation boundary docs/guards | prove scenario path cannot command BAS |

## Phase 6 — agents and cookbooks

| PR train | Deliverable | Key gate |
|---|---|---|
| P6-M0-* | accurate agent specification | code/docs consistency CI |
| P6-M1-* | capability-derived MCP | OpenAPI/tool parity; write approval tests |
| P6-M2-* | stepwise workflow resources | clean-agent usability evaluation |
| P6-M3-* | dual cookbook upgrades | per-rule parity/status/render CI |
| P6-M4-* | agent red-team | authorization/injection/honesty suite |

## Phase 7 — release

| PR train | Deliverable | Key gate |
|---|---|---|
| P7-M0-* | signed release manifest/image set | digest/SBOM/provenance verification |
| P7-M1-* | clean-host/upgrade/rollback | qualification matrix |
| P7-M2-* | backup/restore/retention | clean restore and artifact integrity |
| P7-M3-* | security/privacy | threat-model and adversarial closure |
| P7-M4-* | performance/soak/observability | budgets and sustained soak |
| P7-M5-* | support docs/evidence | independent signoff |

## Dependency spine

```text
P1 truth -> P1 real release/test foundation -> P1 capability closure
   -> P2 contracts -> P2 portable model/Rust inference -> P2 scenario API
   -> P3 studio -> P4 Unity artifact/viewer -> P5 live twin
   -> P6 complete agent workflows -> P7 turnkey qualification
```

Documentation and offline fixture design may move ahead, but no production
runtime PR bypasses its dependency gate.

