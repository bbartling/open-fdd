# Agentic AI and MCP build specification

## Product stance

Open-FDD exposes a safe, vendor-neutral engineering capability layer. External
agents use MCP or documented REST. An embedded chatbot is optional future
product work, not required, and must never become a bypass around permissions,
contracts, provenance, or approvals.

## Agent jobs to be done

An agent should be able to assist, with human review at appropriate gates, in:

1. environment and stack health assessment;
2. site/building/equipment inventory;
3. file import preflight and data-quality diagnosis;
4. point/role mapping suggestions with evidence;
5. FDD rule selection, parameter explanation, execution, and result review;
6. findings clustering and draft engineering dispositions;
7. weather/IDF/twin input readiness;
8. EnergyPlus external-run preparation and artifact review;
9. calibration evidence and assumption review;
10. training dataset/model release inspection;
11. scenario design, execution, comparison, and limitation analysis;
12. Unity build validation/status and spatial binding review;
13. replay/live commissioning diagnosis;
14. report/workbook/twin evidence package assembly;
15. upgrade, backup, restore, and incident troubleshooting.

## Tool design requirements

Every tool declares:

- stable name and semantic version;
- read/plan/write/approve/destructive classification;
- required role and site scope;
- typed JSON Schema input/output;
- idempotency and concurrency behavior;
- time/body/result limits;
- side effects and produced artifacts;
- confirmation/preview requirements;
- audit event type;
- likely errors and safe recovery;
- capability/version prerequisites.

Prefer narrow domain tools to arbitrary SQL, shell, file, HTTP, or code
execution. Large data returns a bounded preview plus an artifact/resource link.

## Safety model

### Read

Read tools may be enabled by default but still enforce JWT/site scope and avoid
returning secrets or unrestricted raw files.

### Plan/preview

A mutation first produces a server-signed, short-lived plan containing target
IDs/revisions, impact, warnings, and a plan hash.

### Write

The write call supplies plan token, `confirm:true`, idempotency key, and expected
revision. Central rechecks identity, authorization, preconditions, and limits.

### Approve/activate/revoke/delete/command

High-impact operations require a stronger role and, where configured, a second
human approval. Plans expire. Model/twin/Unity activation and BAS commands are
never inferred from conversational enthusiasm.

## Prompt-injection and content boundaries

Uploads, point names, findings, reports, notebooks, model cards, IDFs, and Unity
manifests are untrusted data. Tool/resource responses label them as data and do
not allow their text to redefine agent instructions. The server does not accept
paths, URLs, SQL, code, or commands simply because a source artifact requests
them.

## Provenance and honesty

Agent responses and generated reports preserve:

- measured/simulated/replay/surrogate/demo source;
- rule parity/screening status;
- model/twin/release IDs and hashes;
- units, time range, coverage, quality, and domain status;
- assumptions, waivers, and unresolved limitations.

Tools return these as structured fields so honesty does not depend on prompt
memory.

## MCP resources

Publish bounded resources for current capabilities, OpenAPI/schema versions,
rule/twin/model catalogs, dual cookbooks, workflow guides, safety/approval
policy, job/twin evidence manifests, and known limitations. Do not expose
arbitrary filesystem resource templates.

## Evaluation suite

Maintain scripted agent scenarios with expected tool traces and forbidden
actions. Include normal workflow, incomplete inputs, ambiguous mapping,
provisional FDD, OOD model, corrupt Unity archive, cross-site request, stale
plan, repeated write, injected instructions in uploaded content, unavailable
central, and attempted BAS command.

Scores cover task completion, correct tools, minimum privilege, confirmation,
provenance, numerical fidelity, refusal/escalation, and absence of unsupported
claims. A model/provider change reruns the suite; product security does not
depend on a particular model passing it.

## Documentation contract

The public agent docs are generated from or verified against:

- central OpenAPI;
- `/api/capabilities`;
- MCP tool definitions;
- contract schemas;
- SQL registry and cookbook parity matrix;
- supported release manifest.

Stale examples fail CI. Each workflow has a copy-paste read-only quickstart and
a separate mutation/approval example.

## Role packs (Vibe21 community glue)

Do **not** embed Jupyter in the SPA. Parties use portable ZIP lanes plus
role-scoped MCP contexts:

| Role | Spec |
|------|------|
| package-mapping | `docs/mcp-agents/roles/package-mapping.md` |
| surrogate-train | `docs/mcp-agents/roles/surrogate-train.md` |
| unity-webgl-build | `docs/mcp-agents/roles/unity-webgl-build.md` |
| operator-activate | `docs/mcp-agents/roles/operator-activate.md` |

ZIP SoT: `docs/migration/vibe21/ROLE_IMPORT_LANES.md`. Tool catalog:
`docs/mcp-agents/roles/tool-catalog.v1.json`. Model supply is
`model_release.zip` only — never online `joblib.load`. All role tools declare
`bas_write: false` while `BAS_WRITE_AUTHORITY=no`.


