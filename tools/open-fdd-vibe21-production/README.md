# Open-FDD production recovery and Vibe 21 digital-twin program

**Program status:** proposed execution plan based on a static audit of Open-FDD
`b3ff921ec981c3381b24bbfdde55c9c4d6f0ba9c` and Vibe 21
`bcc189a2ae3f3e374b8ffc1ea056971f3032ed7a` on 2026-08-01.

## Mission

Turn the current Open-FDD React/Rust migration and the validated Vibe 21
prototype into one production-quality, local-first building analytics and
digital-twinning product:

```text
CSV / Parquet / Arrow / BACnet -> MQTTS -> Rust central -> DataFusion SQL
                                                   |             |
                                                   |             +-> FDD / analytics
                                                   +-> jobs / twins / scenarios / artifacts
                                                                |
                                      React engineering studio <-+-> Unity WebGL viewer
                                                                |
                                               Rust model inference / external E+ workers
```

The production request path is Rust, DataFusion SQL, Arrow/Parquet, and React.
Python is retained only where it is intentionally valuable:

- offline notebooks and model training;
- the published `open-fdd` PyPI pandas oracle and engineering workbook tools;
- bounded, reproducible data-science and engineering workflows outside the
  production web request path.

There is no production Flask, FastAPI, pandas, scikit-learn, joblib, or
React SPA process. Unity is authored and built outside Open-FDD; Open-FDD
validates and serves an immutable WebGL artifact.

## Why a recovery phase is required

The earlier agents delivered useful architecture: a React SPA, Rust central
contracts, DataFusion SQL registry, job records, Docker recipes, and an MCP
server. They did not deliver the acceptance standard claimed by the Phase 1/2
closeout documents. Examples include a placeholder SVG chart named
`PlotlyHost`, RCx coverage stubs, seeded demo findings in the product UI, a fake
lint command, mock-heavy frontend tests, no published `openfdd-web` image in the
main stack workflow, and 39 of 63 SQL rules that are not oracle-proven. The
documentation also contradicts itself about whether React or React SPA ships.

Phase 1 therefore reopens the migration as an evidence-recovery and
production-hardening program. It does not throw away the existing work.

## Program phases

| Phase | Outcome | Production gate |
|---|---|---|
| [1. Recovery and product truth](PHASE_1_RECOVERY_AND_PRODUCT_TRUTH.md) | React/Rust migration is honestly scoped, fully tested, shipped, and usable | One supported React stack; no demo/stub path masquerades as production |
| [2. Vibe 21 contract and Rust inference](PHASE_2_VIBE21_RUST_TWIN_FOUNDATION.md) | Vibe 21 schemas, assets, scenarios, and model inference are owned by Rust contracts | Golden parity with Python oracle; no Python inference in runtime image |
| [3. Digital Twin Studio](PHASE_3_REACT_DIGITAL_TWIN_STUDIO.md) | Guided React job/twin/calibration/scenario workflow | End-to-end browser workflow over real central APIs |
| [4. Unity WebGL artifact platform](PHASE_4_UNITY_WEBGL_ARTIFACT_PLATFORM.md) | Signed Unity builds are uploaded, validated, versioned, served, and embedded | Same-origin WebGL smoke, security, rollback, compatibility gates |
| [5. Operational/live twin](PHASE_5_OPERATIONAL_TWIN_AND_EDGE.md) | Replay and live telemetry drive the same twin contract | Quality-aware MQTTS ingestion; no control writes by default |
| [6. Agentic engineering and public knowledge](PHASE_6_AGENTIC_MCP_AND_COOKBOOKS.md) | External agents can safely assist every workflow; dual rule knowledge remains public | Capability-derived MCP, approval gates, cookbook parity CI, traceable artifacts |
| [7. Production qualification](PHASE_7_RELEASE_QUALIFICATION.md) | Turnkey release is observable, secure, reproducible, and recoverable | Clean-host install, soak, upgrade, backup/restore, rollback, release evidence |

Phase numbers are ordering constraints, not permission to build everything in
one branch. Each milestone is split into bounded PRs in
[MILESTONE_PR_MATRIX.md](MILESTONE_PR_MATRIX.md).

## Program invariants

1. **Evidence beats status prose.** A checkbox, merged PR, or mocked test is not
   acceptance evidence.
2. **One product UI.** React is the only supported product UI. React SPA may
   remain in an explicitly non-shipping archive until evidence retention
   expires.
3. **One production computation authority.** DataFusion SQL owns deterministic
   FDD/analytics. Rust owns orchestration, validation, persistence, and online
   inference.
4. **Python remains a named oracle/toolchain.** It never silently answers a
   production web request.
5. **Unity is a presentation client.** It does not own truth, persistence,
   permissions, scenario rules, or model selection.
6. **EnergyPlus execution is external and sandboxed.** Central schedules jobs
   and records provenance; a digest-pinned worker executes them.
7. **No fake production data.** Demo fixtures live behind an explicit demo mode
   and are labeled in every response and view.
8. **Stable identities.** Site, building, equipment, point, twin, geometry,
   scenario, model, run, and artifact IDs survive display-name changes.
9. **Schema evolution is additive by default.** Breaking changes require a new
   version, migration, compatibility window, and fixture set.
10. **External-agent first, not embedded-chat first.** MCP and documented REST
    workflows expose product capabilities without shipping provider keys or an
    ungoverned in-dashboard LLM.

## Python boundary

| Surface | Allowed Python | Production request path? |
|---|---|---|
| PyPI `open-fdd` rules/analytics | pandas oracle and examples | No |
| PyPI engineering deliverables | openpyxl/report tooling for engineers/agents | No |
| Notebooks/training | pandas, scikit-learn, EnergyPlus preparation, evaluation | No |
| Model publication | converter/exporter and conformance pack builder | CI/offline only |
| Central/API/worker control plane | None | Yes, Rust |
| Online FDD/analytics | None | Yes, DataFusion SQL + Rust |
| Online model inference | None | Yes, Rust-compatible signed artifact |
| React and Unity WebGL | None | Yes, browser assets |

See [PYTHON_BOUNDARY_AND_MODEL_SUPPLY_CHAIN.md](PYTHON_BOUNDARY_AND_MODEL_SUPPLY_CHAIN.md)
for enforcement details.

EnergyPlus and optional eQUEST integrations follow the external-worker protocol
in [SIMULATION_ENGINE_ADAPTERS.md](SIMULATION_ENGINE_ADAPTERS.md). The Open-FDD
control plane remains Rust; no claim is made that third-party simulation engines
are rewritten in Rust.

## Required reading order for execution agents

1. repository root `AGENTS.md`;
2. this file;
3. [CURRENT_STATE_AUDIT.md](CURRENT_STATE_AUDIT.md);
4. [TARGET_ARCHITECTURE_AND_CONTRACTS.md](TARGET_ARCHITECTURE_AND_CONTRACTS.md);
5. the current phase document;
6. [TEST_RELEASE_AND_ACCEPTANCE.md](TEST_RELEASE_AND_ACCEPTANCE.md);
7. [SIMULATION_ENGINE_ADAPTERS.md](SIMULATION_ENGINE_ADAPTERS.md) when simulation work is in scope;
8. [AGENT_EXECUTION_SYSTEM.md](AGENT_EXECUTION_SYSTEM.md);
9. [prompts/MASTER_PRODUCTION_LOOP.md](prompts/MASTER_PRODUCTION_LOOP.md).

## Immediate decision

Start at Phase 1. Do not begin the Vibe 21 production port on top of disputed UI
and release foundations. Phase 2 contract design may occur in parallel only as
documentation/fixtures; runtime integration waits for all Phase 1 gates.
