# Phase 6 — Agentic engineering, MCP, and public dual cookbooks

## Objective

Let external AI agents safely assist an engineer through every analytics and
digital-twin step using versioned, discoverable, auditable tools. Maintain both
the pandas/PyPI oracle cookbook and production DataFusion SQL cookbook as public
engineering knowledge.

The product does not need an embedded chatbot to satisfy this objective.

## P6-M0 — Correct the agent specification

Update `openfdd_agent_spec` so every live document agrees with code and the
capability ledger:

- React is the sole product UI;
- Rust/DataFusion own production;
- Python boundary is explicit;
- twin/model/Unity concepts and owners are included;
- Vibe 21 is an oracle/source repository, not a production dependency;
- current contracts/crates are described as they exist;
- Phase/status wording is generated or validated;
- all referenced paths and commands are tested.

Required agent reading order: root instructions, ownership, contracts,
capabilities, current phase, acceptance, safety, then bounded prompt.

## P6-M1 — Capability-derived MCP catalog

Generate/check MCP resources and tools against central OpenAPI and
`/api/capabilities`. Organize by workflow:

### Discover and assess

- health/capabilities/version;
- sites/buildings/equipment/points;
- data coverage/quality and mapping gaps;
- FDD registry, parameters, evidence, and parity status;
- twin/model/Unity release status.

### Prepare and analyze

- preview imports and plans;
- validate mappings/roles;
- run bounded FDD/analytics;
- inspect findings and draft dispositions;
- create/inspect replay sessions.

### Build and validate a twin

- create/fork draft twin version;
- attach inputs/evidence;
- queue digest-pinned EnergyPlus work;
- inspect calibration/readiness;
- import/validate model and Unity build artifacts;
- run/compare scenarios;
- build a draft deliverable.

### Approve/publish

Approval, activation, revocation, deletion, command, and external-run operations
are write tools. They require:

- explicit server-side role;
- MCP writes enabled;
- `confirm:true` plus a current preview/plan token;
- idempotency key;
- human-readable impact summary;
- short expiry and stale-revision rejection;
- durable audit record with actor/client/request/artifact hashes.

The server revalidates every condition; the agent prompt is not a security
boundary.

## P6-M2 — Workflow guides and resources

Expose concise MCP resources (or docs returned by pointer) for:

- project/site setup;
- CSV/BAS import and mapping;
- FDD parameter selection and interpretation;
- finding review and engineering disposition;
- weather/IDF/EnergyPlus preparation;
- calibration and G14 evidence;
- training dataset/model publication;
- scenario design and domain warnings;
- Unity WebGL handoff;
- replay/live commissioning;
- reporting and reproducibility export.

Each guide declares prerequisites, safe read operations, mutation approval
points, expected artifacts, common failure modes, and stop/escalation criteria.

## P6-M3 — Permanent dual expression cookbooks

Maintain online:

1. **Pandas/PyPI cookbook** — readable expressions and examples for engineers,
   notebooks, AI agents, spreadsheets, and the characterization oracle.
2. **DataFusion SQL cookbook** — production query/rule expressions, schema,
   parameters, null/time/window behavior, and performance notes.
3. **Parity matrix** — per-rule identity, implementation, status, fixture,
   divergence, and evidence.

For every rule change, CI verifies:

- unique stable identity and aliases;
- registry/SQL file/cookbook headings and metadata agree;
- pandas implementation/docs remain present where promised;
- schema/roles/units/defaults/ranges match contracts;
- golden/adversarial fixture paths exist for proven status;
- rule counts cannot shrink without an approved tombstone/migration;
- rendered docs links and runnable snippets work;
- screening/provisional language is visible online.

The machine manifest contains identity/metadata, not duplicated formula bodies.

## P6-M4 — Agent evaluation and red-team tests

Test representative agents from a clean environment:

- can complete read-only assessment without shell/database access;
- cannot cross site boundaries;
- cannot turn a preview into a write without explicit confirmation;
- cannot activate an unqualified model/twin/Unity build;
- cannot smuggle path traversal or untrusted artifact content;
- cannot execute arbitrary SQL, Python, IDF commands, or BACnet writes;
- receives useful field errors and recovery instructions;
- preserves source/provenance/uncertainty in summaries;
- does not describe screening FDD or simulated ML as proven truth.

## Phase 6 exit gates

- MCP/OpenAPI/capability inventories agree automatically.
- All mutations are role-gated, previewed, confirmed, idempotent, and audited.
- A clean external agent can complete a representative digital-twin workflow
  using documented MCP tools and human approvals.
- Dual cookbooks render online and parity CI passes.
- Agent docs have no stale React SPA/contract/runtime claims.
- No secrets, arbitrary code execution, arbitrary SQL, or direct model-provider
  keys are required by the Open-FDD stack.

