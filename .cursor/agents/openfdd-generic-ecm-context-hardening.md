# Open-FDD generic ECM context and calculation hardening

You are the implementation agent for a repository-wide improvement to Open-FDD's generic energy conservation measure calculation context. Start by reading `AGENTS.md`, `openfdd_agent_spec/AGENTS.md`, `openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md`, `docs/ecm/agent-context.md`, `docs/ecm/engineering-calcs.md`, `openfdd_agent_spec/DATA_CONTRACT.md`, and the active Wave S/U plans. Reconcile this work with the current branch and PR trail before editing. Do not revive superseded architecture or duplicate calculators already present in `open_fdd.ecm_engineering`.

## Objective

Make it possible for a future external AI agent to create transparent, reproducible, generic ECM screening calculations from Open-FDD evidence without guessing site facts, confusing assumptions with observations, hiding spreadsheet math, or double counting interacting measures.

The implementation must remain vendor-neutral and building-neutral. It must work for CSV packages, Haystack/RDF models, historian data, local standalone deployments, and JWT-scoped cloud deployments. Python remains an external/PyPI engineering tool and must not be added to the Rust central/web product request path.

## Required first step

Audit the current implementation and create or update an executable `.cursor/plans/*.plan.md` file before changing product code. The plan must identify what already exists, what is partially implemented, what is missing, which old plan rows are superseded, and the exact tests that will establish each claim. Do not mark a requirement complete from documentation alone.

## Context contract to implement

Design a stable, versioned, machine-readable ECM context envelope. Prefer extending existing contracts over adding parallel formats. The envelope must support these sections:

1. **Scope and identity**
   - `schema_version`, `building_id`, tenant scope, equipment IDs, equipment types, timezone, unit system, retrieval timestamp, API/package version, and source revision.
   - Preserve tenant isolation. Foreign building and equipment IDs must deny cleanly.

2. **Equipment evidence**
   - Separate physical assets such as supply fan, return fan, pump, motor, VFD, chiller, boiler, coil, and meter.
   - Carry nameplate and measured quantities with units: hp, kW, efficiency, capacity, airflow, head/static pressure, temperature, flow, fuel input, COP/EER, and other quantities already supported by the engineering vocabulary.
   - Every value needs an evidence class and provenance: observed historian value, meter, BAS point, nameplate, TAB, manufacturer data, user supplied, derived, or assumption.
   - A fan pair must not silently share one command. Encode the actual command/power point per asset or a documented proxy relationship with a warning.

3. **Resolved point roles and data quality**
   - Return resolved role, source point, units, transform, sample window, sample count, valid percentage, gap policy, outlier percentage, min/median/mean/p95/max, and quality warnings.
   - Preserve source timestamps. Do not replace invalid timestamps with epoch zero or current time.
   - Reject or warn on incompatible units, implausible values, missing identities, ambiguous mappings, and duplicate/conflicting roles.

4. **Baseline metrics**
   - Include the observed window and calculation method for runtime, load, speed, temperature, pressure, flow, ton-hours, fuel, occupancy, and weather variables as applicable.
   - Distinguish observed totals from annualized or weather/calendar-normalized values.
   - Annualization must carry method version, denominator, extrapolation period, calendar source, weather station/source, and uncertainty or warnings.

5. **ECM scenario**
   - A versioned scenario object must identify the ECM module/calculator, baseline condition, proposed condition, approved sequence or engineering rationale, constraints, realization factor, effective dates, author, and review status.
   - Support generic parameters without hard-coding Building 100, a vendor, campus, point suffix, city, or utility.
   - Static pressure reset scenarios should be capable of storing minimum/maximum setpoint, trim/respond step, response interval, critical-zone criteria, ventilation constraint, fan minimum speed, baseline/proposed speed distribution, and pilot evidence.

6. **Tariff and finance context**
   - Energy rate, demand rate, ratchet, on-peak periods, fuel rates, escalation, effective dates, currency, source, and avoided-cost method.
   - Missing tariff data must leave monetary or demand results visibly unavailable or marked as an assumption. It must never invent a client tariff.

7. **Calculation result and provenance**
   - Return calculator/module name, package version, calculator version or formula hash, complete input snapshot, units, raw result, realization-adjusted result, warnings, and deterministic test-vector identifier.
   - Keep Excel formulas visible. The Python `calculate(...)` result is an independent referee and must not replace formula cells with hard-coded values.
   - State whether a result is screening, validated, or submission-ready. Only an explicit human review may set submission-ready.

8. **Measure interactions**
   - Add interaction metadata such as `measure_id`, interaction group, calculation order, affected end uses, affected hours, and before/after dependencies.
   - A combined schedule plus fan reset case must apply reset savings only to remaining runtime, or document another valid interaction method. Summing overlapping standalone savings is a failing test.

9. **Missing-evidence response**
   - Return structured `missing_evidence`, `assumptions_required`, `blocking_issues`, and `recommended_measurements` arrays.
   - The agent should still produce a clearly labeled screening calculation when safe assumptions are supplied, but it must refuse rebate-ready claims when required evidence is absent.

## Generic ECM coverage

Apply the contract across the current ECM catalog, not only fans. At minimum, create representative mappings and tests for:

- fan/static-pressure reset and fan schedules;
- pump VFD/reset;
- boiler efficiency/reset;
- chiller kW/ton, CHW reset, and condenser-water reset;
- economizer and outside-air measures;
- DCV and unoccupied outside-air reduction;
- heating/cooling schedule alignment and optimal start;
- dirty filter, motor efficiency, lighting controls, and other existing workbook modules where sufficient context exists.

Do not fabricate equivalence between ECMs with different evidence requirements. A module may remain screening-only if the repository lacks a suitable validated method; document that status honestly.

## Data model and graph requirements

- Reuse and extend the Open-FDD engineering quantity vocabulary and Haystack/RDF rollout contract.
- Keep JSON ZIP ingest/export backward compatible. RDF/Turtle must remain a semantic interchange and validation representation, not a forced replacement for compact JSON packages.
- Use explicit typed graph relationships such as equipment containment, `servedBy`, meters, points, motors, fans, and ECM applicability. Do not implement graph traversal with grep or arbitrary text search.
- Use SPARQL or the repository's approved typed graph projection for graph queries, with tenant/building scope applied before traversal.
- Add SHACL or equivalent repository validation for units, cardinality, provenance, tenant ownership, and physical-asset relationships where the current rollout permits it.
- Preserve unknown vendor extensions during import/export when safe and defined by the compatibility contract.

## Agent API/tooling requirements

Prefer a small set of composable read-first tools instead of one opaque "calculate everything" endpoint. Audit whether existing REST/MCP tools can expose:

- building/equipment inventory and graph neighborhood;
- ECM-ready evidence/context for selected equipment and time window;
- role resolution and quality summary;
- baseline metrics;
- scenario validation;
- deterministic Python calculator invocation or an exportable input payload;
- calculation provenance and readiness assessment.

All tools must honor JWT tenant scope, avoid returning credentials or sensitive deployment details, bound query size/time, and supply actionable errors. Writes or scenario persistence must retain the existing explicit confirmation policy.

## Excel and rebate-audit requirements

Update the agent guidance so generated workbooks contain, at minimum:

- executive summary;
- editable input/assumption cells visually distinct from observed evidence;
- units and provenance beside each input;
- visible formulas and equation descriptions;
- baseline, proposed, raw savings, realization, and interactive combined cases;
- Python package cross-check with tolerance;
- missing-evidence and rebate-readiness checklist;
- no secrets, tokens, or passwords;
- no hidden hard-coded savings results.

Document that annual cost and demand savings remain separate. Demand savings require an interval-demand method and tariff context; multiplying energy savings by a demand rate is prohibited.

## Required tests

Add meaningful permanent tests at the narrowest appropriate layers. Include at least:

1. Contract/schema validation and backward-compatible JSON round-trip.
2. RDF/Turtle projection and scoped graph traversal tests where implemented.
3. Tenant A cannot request Tenant B ECM context, graph nodes, equipment, calculations, or exports.
4. Separate supply/return fan assets retain distinct point and provenance links.
5. Unit conversion and incompatible-unit rejection tests.
6. Missing-nameplate and missing-tariff cases return structured gaps and stay screening-only.
7. Runtime uses timestamp delta integration with the documented gap cap, including irregular and duplicate timestamps.
8. Annualization identifies observed versus normalized values and never labels an extrapolation as observed.
9. Fan affinity and schedule calculations reconcile with `open_fdd.ecm_engineering.calculate(...)` within a declared tolerance.
10. A combined schedule plus static-reset case proves no overlap double count.
11. Known-answer test vectors for at least one fan, one plant, one outside-air, and one fuel ECM.
12. Spreadsheet/template tests verify formulas remain formulas and assumptions are not written into formula cells.
13. API/MCP responses contain calculator/package provenance and no credentials or tokens.
14. Stress test representative many-building/many-equipment context generation with bounded memory, query count, response size, and latency. Record the dataset size and thresholds; a command that did not execute is not PASS.

Do not create tests that only restate implementation internals. Include negative, boundary, malformed-input, tenant-isolation, and deterministic known-answer cases.

## Documentation and durable AI context

Update the canonical sources rather than adding an isolated essay:

- `openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md`;
- `docs/ecm/agent-context.md`;
- `docs/ecm/engineering-calcs.md`;
- `openfdd_agent_spec/DATA_CONTRACT.md`;
- data-model/Haystack/RDF docs affected by the implementation;
- REST/MCP tool docs and examples;
- GitHub Pages navigation where applicable;
- capability ledger, milestone tracker, and active plan evidence.

Add one complete generic example using synthetic data and no private deployment details. Show evidence retrieval, gap assessment, scenario creation, workbook inputs, Python referee output, interaction handling, and final readiness state.

## Evidence and anti-cheating rules

- Do not claim completion from a file existing, a test being skipped, a mock returning 200, or documentation describing intended behavior.
- Record the exact commands, exit codes, test counts, relevant output summaries, and artifact paths in the active evidence/bug tracker.
- Distinguish local unit/integration results, CI results, GHCR candidate smoke, Railway test deployment, and physical OT-lab evidence.
- Never mark unavailable licensed tools, missing OT hardware, or unexecuted deployment tests PASS. Use explicit BLOCKED or Soft-OPEN states with owner and closure evidence.
- Do not expose credentials, tokens, customer data, private hostnames, or exploit details in fixtures, logs, docs, plans, commits, or PR text.
- Preserve unrelated work in the dirty tree. Do not reset, force push, delete `workspace/`, remove volumes, or run destructive Docker cleanup.
- On the low-RAM bench, do not build central/web/fieldbus images locally. Use targeted lightweight tests and CI/GHCR according to repository policy.

## Required deliverables

1. An updated executable Cursor plan with requirement-to-file-to-test traceability.
2. The versioned ECM context/schema and typed code changes.
3. Backward-compatible adapters for existing package/data-model inputs.
4. Read-first REST/MCP exposure as justified by the architecture audit.
5. Updated PyPI calculator/workbook context only where gaps are proven; do not fork existing math.
6. Permanent tests and known-answer fixtures.
7. Updated canonical agent, ECM, data-contract, graph, API, and Pages documentation.
8. Stress and tenant-isolation evidence.
9. A completion report listing implemented, validated, blocked, and deferred items without collapsing those states.

## Completion standard

The work is complete only when a fresh external agent can start from canonical repository context, select a generic building and equipment scope, retrieve evidence with provenance and quality, identify missing inputs, create a formula-visible ECM workbook, reconcile supported calculations to the packaged Python oracle, handle interacting measures without double counting, and state an honest readiness level. The same workflow must deny foreign-tenant data and must not depend on Building 100, any vendor-specific identifier, or undocumented tribal knowledge.
