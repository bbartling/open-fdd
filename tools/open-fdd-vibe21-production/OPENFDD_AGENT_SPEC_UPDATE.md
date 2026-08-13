# Required updates to `openfdd_agent_spec`

## Purpose

The existing agent specification contains valuable architecture and workflow
material, but live documents conflict with code and with each other. Execute
this checklist in Phase 1 and extend it in later phases.

## Authority order

Replace ad hoc status prose with this authority order:

1. root `AGENTS.md` for non-negotiable architecture/safety;
2. machine-readable ownership/capabilities/schema/release manifests;
3. current phase and acceptance specification;
4. generated OpenAPI/MCP/rule catalogs;
5. workflow guides and examples;
6. archived history.

Nested instructions may specialize but never contradict a higher authority.

## Immediate corrections

- `frontend/web`: mark React SPA archive/oracle-only; remove “current
  default product UI.”
- `docs/agent/index.md`: replace React SPA runtime/UI table with React web and
  Rust central; link current MCP catalog.
- `frontend/web/README.md`: remove Phase 1 scaffold/default-off language after
  supported React release qualification.
- `openfdd_agent_spec/AGENTS.md`, `ARCHITECTURE.md`, `DATA_CONTRACT.md`,
  `VERSIONING.md`, `MILESTONE_A.md`, `ownership.yaml`, and checkpoints: reconcile
  the actual `crates/openfdd_contracts` implementation and current status.
- Cookbook pages: remove “one React SPA” claims while preserving pandas as
  oracle.
- GHCR/runbook docs: name images actually published and stop calling archived
  React SPA `openfdd-web` the product.

## New specification sections

Add ownership and instructions for:

- twin/twin-version and stable identity;
- observation/time/quality contract;
- model release and Rust inference;
- external EnergyPlus worker;
- Unity build artifact and browser bridge;
- React Digital Twin Studio;
- replay/live MQTTS twin;
- MCP approval/audit safety;
- Python boundary/model supply chain;
- dual cookbook permanent ownership;
- qualification evidence and status semantics.

## Skill changes

Update the Open-FDD migration skill so it:

- does not state Phase 1/2 are complete unconditionally;
- reads the capability ledger and current evidence;
- routes to the current phase;
- forbids completion claims without qualification manifest;
- treats Vibe 21 as a frozen oracle and asset source;
- requires Rust online inference and secure Unity artifact serving;
- preserves both cookbooks and PyPI engineering tools;
- invokes real-stack browser and clean-host gates for product changes.

Add focused skills only where repeated work justifies them:

- `openfdd-twin-contracts`;
- `openfdd-rust-model-inference`;
- `openfdd-unity-webgl-artifacts`;
- `openfdd-agent-mcp-safety`.

Each skill must have a complete description, bounded trigger conditions,
required reading, execution loop, validation, and stop/escalation conditions.

## Checkpoint format

Replace unchecked/checked prose with records that include status, commit, PR,
capability IDs, evidence manifest, limitations, implementer, verifier, and date.
Historical completion remains historical; a reopened gate is recorded rather
than overwritten.

## CI guards

- referenced path/link exists;
- no live docs use retired topology language;
- status/capability/route/tool/schema versions agree;
- required instructions have no TODO placeholder descriptions;
- archived docs are excluded from current search/index or visibly labeled;
- generated examples validate against current schemas;
- no private machine paths/IPs/secrets appear.

