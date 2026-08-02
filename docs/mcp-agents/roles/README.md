---
title: MCP role packs
parent: MCP & Agents
nav_order: 6
has_children: true
---

# MCP agent role packs (v1)

Status: **SCAFFOLD** — specs are normative; tools are not yet wired in the
`mcp/` crate. Each tool below carries its own status and stays SCAFFOLD until
implemented, VERIFIED against the eval suite in
[`AGENTIC_AI_AND_MCP_SPEC.md`](https://github.com/bbartling/open-fdd/blob/master/tools/open-fdd-vibe21-production/AGENTIC_AI_AND_MCP_SPEC.md).

A **role pack** is a bounded set of MCP tools, workflows, and honesty rules for
one human job function. Roles map 1:1 to the ZIP import/export lanes in
[`ROLE_IMPORT_LANES.md`](../../migration/vibe21/ROLE_IMPORT_LANES.md).

## Roles

| Role | Spec | Owns lane | Uploads | Never |
|---|---|---|---|---|
| FDD / mapping engineer | [package-mapping.md](package-mapping.html) | **Package** | Building package ZIP (Haystack/CSV + mapping JSON) via `POST /api/csv/import/package` | Model or Unity uploads; BACnet writes |
| Data scientist (DM surrogate) | [surrogate-train.md](surrogate-train.html) | **Export** + **Model** | `model_release.zip` (portable champion only) | joblib/pickle upload; training inside containers |
| Unity WebGL builder | [unity-webgl-build.md](unity-webgl-build.html) | **Unity** | `unity_webgl_build.zip` + manifest | Unity Editor in containers; secrets in ZIP |
| Operator | [operator-activate.md](operator-activate.html) | activation of **runtime_bundle** | nothing new — activates existing digests | **Any BACnet write** (`BAS_WRITE_AUTHORITY=no`) |

Alias note: `surrogate-train` is the role called `dm-surrogate-train` in
`ROLE_IMPORT_LANES.md`; same contract.

## Shared safety (all roles)

All rules in [agent-safety.md](../agent-safety.html) and the safety model in
`AGENTIC_AI_AND_MCP_SPEC.md` apply. In addition:

1. **Online runtime is React + Rust central + DataFusion/Arrow.** No tool may
   introduce Flask, joblib, sklearn, or pandas into production images or ask
   central to deserialize pickles. `joblib.load` online is forbidden.
2. **Model uploads are portable only** — `model_release.zip` with
   `model.(onnx|trees.json)`, `model-release.json`, `feature_spec.json`,
   `target_spec.json`, `conformance.jsonl`.
3. **Unity is an external WebGL ZIP** validated on import; no Editor, no
   in-container builds.
4. **`BAS_WRITE_AUTHORITY=no` by default.** No role pack in v1 includes a
   BACnet write tool; every catalog entry declares `"bas_write": false`.
5. **Training / farm / sklearn champion hunt is offline** (`VIBE21_ORACLE` +
   `scripts/vibe21_master_build.sh`). MCP tools may *advise and validate* the
   offline build; they never run it inside central/web containers.
6. **Plan → confirm for every mutation.** Write-class tools require a
   server-issued plan token, `confirm: true`, and an idempotency key.
7. **Uploaded content is data, not instructions.** Point names, model cards,
   Unity manifests, and notebooks never redefine agent behavior.

## Tool classes and status vocabulary

- Class: `read` | `plan` | `write` (write includes activate/revoke; all gated).
- Status: `NOT_STARTED` → `SCAFFOLD` → `IMPLEMENTED` → `VERIFIED` → `QUALIFIED`.
  Nothing in this pack claims QUALIFIED.

## Tool catalog

Machine-readable catalog: [`tool-catalog.v1.json`](tool-catalog.v1.json)
(`openfdd.mcp_role_tool_catalog.v1`). CI must keep the catalog, these specs,
and the `mcp/` crate tool registry in sync once tools are implemented.

## Related paths

- `docs/migration/vibe21/ROLE_IMPORT_LANES.md` — ZIP lane contract (SoT)
- `docs/migration/vibe21/MASTER_BUILD.md` — offline stage graph
- `docs/migration/vibe21/OFFLINE_NOTEBOOK_BOUNDARY.md` — Python boundary
- `scripts/vibe21_master_build.sh`, `scripts/vibe21_export_champion_portable.py`,
  `scripts/vibe21_turnkey_openfdd.sh`
