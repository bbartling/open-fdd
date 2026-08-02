---
title: "Role: unity-webgl-build"
parent: MCP role packs
nav_order: 3
---

# Role pack: `unity-webgl-build` — Unity WebGL builder

Status: **SCAFFOLD** (spec normative; tools not yet in `mcp/` crate).

## Mission

Produce a Unity **WebGL** build in the Unity Editor (outside all containers),
package it as `unity_webgl_build.zip` with `WEBGL_BUILD_MANIFEST.json` /
`unity-build.json`, and get it validated + imported so central serves it
same-origin under `/twins/{twin}/builds/{build}/…` for the React `/twin` host.

**Hard law:** Unity is external only. No Unity Editor, license, or build step
inside Open-FDD containers or CI images.

## Required ZIP members

| Member | Required | Notes |
|---|---|---|
| `index.html` | yes | entry point served same-origin |
| `Build/*` | yes | loader `.js`, `.wasm`, `.data`, framework files |
| `unity-build.json` or `WEBGL_BUILD_MANIFEST.json` | yes | build ID, Unity version, per-file SHA-256, total size, compression mode |
| `TemplateData/*` | recommended | template assets |
| Secrets/tokens/`.env`/editor logs | **forbidden** | validation fails the ZIP |

**Decompression fallback:** if members ship Brotli/gzip pre-compressed, the
manifest must declare the compression mode and the build must include the
Unity decompression fallback (or central must serve correct
`Content-Encoding`). A build that only works with special server config and
doesn't declare it fails validation.

## Threat model (brief)

| Threat | Control |
|---|---|
| **Zip-slip** (`../` or absolute paths) | Reject any entry escaping the extraction root; validation, not sanitization. |
| **Zip bomb** (compression-ratio abuse) | Enforce max compressed size, max uncompressed size, max member count, max ratio; fail closed. |
| **Oversize builds** | Hard size cap (configurable; oracle build ≈ 68 MiB is the reference scale). |
| **Manifest/member mismatch** | Recompute SHA-256 per member; any mismatch fails import. |
| **Embedded secrets** | Pattern scan for token/key material in text members; fail on hit. |
| **Manifest as instruction channel** | Manifest text is data; it never changes agent behavior or server paths. |

## MCP tools

| Tool | Class | Status | Inputs | Outputs | Side effects |
|---|---|---|---|---|---|
| `unity_zip_validate` | read | SCAFFOLD | ZIP ref | member inventory, required-member check, zip-slip/bomb/size verdicts, secret-scan result, compression mode | none |
| `unity_zip_hashes` | read | SCAFFOLD | ZIP ref | per-member SHA-256 + total, diff vs manifest | none |
| `unity_build_import_plan` | plan | SCAFFOLD | validated ZIP ref, twin_id | plan token, target `unity_build_id`, size/impact summary | plan record |
| `unity_build_import_execute` | write | SCAFFOLD | plan token, `confirm:true`, idempotency key | `unity_build_id`, served base path `/twins/{twin}/builds/{build}/` | immutable build stored (not active) |
| `unity_build_activate` | write | SCAFFOLD | twin_id, unity_build_id, plan token, `confirm:true` | active build pointer update | runtime_bundle unity pin changed |
| `unity_index_smoke` | read | SCAFFOLD | twin_id, build_id | HTTP status of `index.html` + `Build/*` loader files, MIME correctness (`application/wasm`, JS), CSP header check | none |

## Workflow

1. Build WebGL in the Editor; pack ZIP + manifest (offline; master-build
   `unity` stage can do the packing from `flask_app/webgl/`).
2. `unity_zip_validate` → must be fully green (members, threat checks, no
   secrets).
3. `unity_zip_hashes` → manifest hashes match recomputed hashes exactly.
4. `unity_build_import_plan` → human confirms → `unity_build_import_execute`.
5. `unity_index_smoke` against the served path — correct MIME for `.wasm`/JS
   and 200s on all loader members.
6. `unity_build_activate` only on explicit request (activation usually flows
   through the operator's runtime_bundle instead).

## Errors and recovery

| Error | Recovery |
|---|---|
| Missing `index.html` / `Build/*` | Rebuild/re-pack; import is blocked, no partial import. |
| Hash mismatch | Re-pack from the build output directory; never edit the manifest to match. |
| Zip-slip / bomb verdict | Reject; obtain a clean build; do not attempt server-side sanitization. |
| Wrong MIME on smoke | Fix central/nginx config (align `frontend/web/nginx.conf`), re-smoke; not a ZIP problem. |
| Secret detected | Purge the secret from the Unity project, rotate it, rebuild. |

## Acceptance checklist

- [ ] `unity_zip_validate` green: required members, no path escapes, within size/ratio caps, no secrets.
- [ ] Manifest SHA-256s match recomputed hashes for every member.
- [ ] Compression mode declared; decompression fallback present or server encoding confirmed.
- [ ] Imported via plan token; `unity_build_id` and served base path reported.
- [ ] `unity_index_smoke` green including wasm MIME.
- [ ] No Unity Editor or build tooling ran inside any container.
