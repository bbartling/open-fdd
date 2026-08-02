# Role import / export lanes (community contract)

Three ZIP pickers + one export — **portable digests only** in production.

| Lane | Actor | Upload | Key files (required) |
|---|---|---|---|
| Package | FDD / mapping | Building package ZIP | Haystack/CSV members + mapping JSON (column→role) — existing `/api/csv/import/package` |
| Unity | WebGL builder | `unity_webgl_build.zip` | `index.html`, `Build/*`, `unity-build.json` / `WEBGL_BUILD_MANIFEST.json` |
| Model | Data scientist | `model_release.zip` | `model.(onnx\|trees.json)` + `model-release.json` + `feature_spec.json` + `target_spec.json` + `conformance.jsonl` |
| Export | Data scientist | download | Training ZIP: Parquet/Arrow + specs + twin digests (train offline; re-upload model_release) |

**Forbidden online:** arbitrary `joblib`/`pickle` deserialization in central/web.
Offline vibe21 may still produce joblib; `scripts/vibe21_export_champion_portable.py` converts to the model_release ZIP.

MCP role packs (normative specs; tools SCAFFOLD until `mcp/` crate wires them):

| Role id | Spec |
|---|---|
| `package-mapping` | [`docs/mcp-agents/roles/package-mapping.md`](../../mcp-agents/roles/package-mapping.md) |
| `surrogate-train` (alias `dm-surrogate-train`) | [`docs/mcp-agents/roles/surrogate-train.md`](../../mcp-agents/roles/surrogate-train.md) |
| `unity-webgl-build` | [`docs/mcp-agents/roles/unity-webgl-build.md`](../../mcp-agents/roles/unity-webgl-build.md) |
| `operator-activate` | [`docs/mcp-agents/roles/operator-activate.md`](../../mcp-agents/roles/operator-activate.md) |

Catalog: [`docs/mcp-agents/roles/tool-catalog.v1.json`](../../mcp-agents/roles/tool-catalog.v1.json).
