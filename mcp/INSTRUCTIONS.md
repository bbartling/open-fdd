# Open-FDD MCP server instructions

Read-first MCP sidecar for the Rust edge bridge. Requires JWT via `OPENFDD_MCP_TOKEN` or unauthenticated `/api/health` only.

## Twin / ECM / EnergyPlus?

**This server is FDD + sites + historian only.** For WattLab Twin calibrate, Fuel, ECM Excel, or IDF surgery, read:

→ [`docs/mcp-agents/companion-wattlab-energyplus.md`](../docs/mcp-agents/companion-wattlab-energyplus.md)

Wire **EnergyPlus-MCP** (or `wattlab energyplus-ensure` / `mcp-exec`) separately. Never expect openfdd-mcp to patch IDFs.

**MCP tools:** `openfdd_agent_context_pointers` — companion doc paths + dual-site checklist (read-only).

## Vibe21 / DM twin — role packs (not Jupyter-in-SPA)

Community glue is **four MCP role contexts** mapped to portable ZIP lanes — never stuff notebooks into the SPA or load joblib online:

| Role | Spec | Lane |
|------|------|------|
| Package / mapping | [`docs/mcp-agents/roles/package-mapping.md`](../docs/mcp-agents/roles/package-mapping.md) | Building package ZIP |
| Surrogate train | [`docs/mcp-agents/roles/surrogate-train.md`](../docs/mcp-agents/roles/surrogate-train.md) | Training export → offline master_build → `model_release.zip` |
| Unity WebGL | [`docs/mcp-agents/roles/unity-webgl-build.md`](../docs/mcp-agents/roles/unity-webgl-build.md) | `unity_webgl_build.zip` |
| Operator | [`docs/mcp-agents/roles/operator-activate.md`](../docs/mcp-agents/roles/operator-activate.md) | Activate bundle + predict smoke; **no BAS writes** |

Index: [`docs/mcp-agents/roles/README.md`](../docs/mcp-agents/roles/README.md). Catalog: [`tool-catalog.v1.json`](../docs/mcp-agents/roles/tool-catalog.v1.json) (SCAFFOLD until wired in `mcp/`). ZIP SoT: [`docs/migration/vibe21/ROLE_IMPORT_LANES.md`](../docs/migration/vibe21/ROLE_IMPORT_LANES.md).

## Login / credentials (agents)

MCP runs on the **host** and needs a **Bearer JWT** in `OPENFDD_MCP_TOKEN`. Prefer a dedicated **agent** identity — never put the admin password into MCP config.

| Source | Path / env |
|--------|------------|
| Railway / central | `OPENFDD_AGENT_PASSWORD` → `POST /api/auth/login` `{ "username":"agent", "password":"…" }` → operator JWT |
| Admin mint | Admin JWT → `POST /api/auth/agent-token` `{ "ttl_secs": 3600 }` |
| LAN bootstrap (legacy) | `workspace/bootstrap_credentials.once.txt` — lines `integrator: …`, `agent: …` |
| Env override (scripts) | `OPENFDD_INTEGRATOR_PASSWORD`, `OPENFDD_AGENT_PASSWORD` |
| Shell helper | `scripts/openfdd_auth_lib.sh` → `openfdd_auth_login_token` |

**MCP tools:**

- `openfdd_auth_credentials_hint` — paths and roles (no secrets)
- `openfdd_auth_login` — `{ "role": "agent" }` → JWT for `OPENFDD_MCP_TOKEN` when bootstrap/env passwords exist

Railway: keep MCP on private networking; see [RAILWAY_DEPLOYMENT.md](../docs/operations/RAILWAY_DEPLOYMENT.md). Works with **Cursor, Claude Desktop, Codex CLI, OpenClaw**, or any MCP host. Open-FDD does **not** ship a built-in chatbot — connect external agents through this stdio server or JWT REST.

### Railway CLI vs this MCP

| Tool | Purpose |
|------|---------|
| **`railway` CLI** (`@railway/cli`) | Deploy/re-pin hub images, vars, logs on Railway (`gleaming-cooperation`). Skill: [`openfdd-railway-cli`](../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md). Docs: [`RAILWAY_DEPLOYMENT.md`](../docs/operations/RAILWAY_DEPLOYMENT.md). |
| **Local Compose (`react-ot`)** | Firewall / on-prem hub — **plain HTTP** UI `:3000` / API `:8080`; **no product TLS yet**. Docs: [`LOCAL_DEPLOYMENT.md`](../docs/operations/LOCAL_DEPLOYMENT.md). |
| **Stress closeout** | After tip re-pin: `run_all` → synth59 → gate17 → B100 → Creekside → gate19 → optional light ZAP on Railway public URL. Docs: [`STRESS_CLOSEOUT.md`](../docs/operations/STRESS_CLOSEOUT.md) · skill [`openfdd-stress-closeout`](../openfdd_agent_spec/skills/openfdd-stress-closeout/SKILL.md). |
| **Railway’s optional MCP** (`railway setup agent`) | Railway platform deploys/docs — **not** HVAC FDD. |
| **`openfdd-mcp` (this package)** | FDD / sites / historian tools against central via `OPENFDD_MCP_TOKEN`. |

Do not point Cursor at Railway MCP and expect Open-FDD AFDD tools. For cloud lab: keep central private; mint agent JWT; set `OPENFDD_API_BASE` to a reachable central URL (private mesh or VPN), not the public web SPA alone for write tools. For local: `OPENFDD_API_BASE=http://127.0.0.1:8080` (HTTP).

## Model + FDD wiresheet

After `openfdd_model_assignments_save` (with `confirm: true`), the **FDD wiresheet** on Model → **FDD wiresheet** tab auto-syncs (`graph:live-fdd-validation`). Or call `openfdd_fdd_wires_sync` / `openfdd_fdd_wires_propose`.

## Package authoring (any BAS job)

Empty analytics after import = **missing roles**, not a broken MCP tool or FDD engine. Stamp `equipType`; Haystack `points` → SQL via `haystack_point_to_role`; weather at `{building}/weather/`; motor ≠ compressor ≠ valve. Full table: [`docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md) · aliases [`ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md).

**Live MQTT (Railway `bldg2`):** healthy `ingest_ok` with blank Overview usually means live tags (`zonetemp`, `sa_t`) were not normalized to cookbook `zone_t` / `sat`. Product aliases: `normalize_role` in `fdd_core`. Do not rename remote OT devices. CSV package uploads need JWT + web nginx body ≥128m.

Use existing `openfdd_csv_import_*` + `openfdd_csv_package_append`. SCAFFOLD `package_preflight` / `mapping_suggest` are **not** in this crate.

## CSV agent workflow (agent-first ingest)

1. **`openfdd_ingest_contract`** — read historian_wide_csv + commissioning mold before cleaning.
2. **Agent sandbox** — reshape CSVs in `workspace/agent-toolshed/<job-id>/` (gitignored; never commit Python/CSV to repo).
3. **`openfdd_csv_import_preview`** — `files: [{filename, path}]` from host or `content_base64`.
4. **`openfdd_csv_import_plan`** — `session_id` + `plan` (mode, files, timezone, value_columns).
5. **`openfdd_csv_import_preflight`** — **required**; loop until `verdict: "pass"` (read `validation.checks` + `agent_hints`).
6. **`openfdd_csv_import_execute`** — `confirm: true` + write gate → Arrow + historian (fail-closed unless preflight pass).
7. **Hourly IoT** — seed package then **`openfdd_csv_package_append`** (`confirm: true`, `building_id`, `equipment_id`, `csv`).
8. **AFDD routine (after append)** — `openfdd_fdd_session_config` PUT `params` → **`openfdd_fdd_run`** (`mode: registry`, `building_id`, optional `rule_ids`). Bench reference: `scripts/csv_flood_afdd_routine_sim.py` + `scripts/fixtures/b50_afdd_routine.json` ([doc](../docs/agent/CSV_FLOOD_AFDD_ROUTINE.md)).
9. Optional **`openfdd_model_commissioning_import`** — sites/equipment/points/assignments/rules bundle.
10. **`openfdd_fdd_rule_test_sql`** → **`openfdd_rules_batch`** (not `openfdd_fdd_run` for saved rules).
11. **`openfdd_reports_from_fdd_sql_run`** — PDF with `download_url`.

Composite: **`openfdd_integration_smoke`** — `{ import_dir?, session_id?, confirm?, run_fdd?, run_report? }`.

**E+ dump / clustering (offline):** host scripts `scripts/agent_eplus_dump.sh` + `scripts/eplus_dump_clustering_export.py` — not MCP tools yet. Doc: [`docs/agent/EPLUS_DUMP_CLUSTERING.md`](../docs/agent/EPLUS_DUMP_CLUSTERING.md).

**Parity:** synthetic golden = `scripts/synthetic_59_*.py` (OpenFDD-only). Vibe19 B100 dump-parity retired (`scripts/retired/vibe19-parity/`).

Helper script (bash only): `scripts/openfdd_csv_preflight.sh <session_id>`.

### Vendor long-format CSV (preprocess example)

Field exports such as `hvac_systems_CLEANED/` are **long-format** BAS grids — not historian-wide shape. This is a **preprocess example**, not product hardcoding. Agent must pivot before preflight pass.

1. Copy raw files to `workspace/agent-toolshed/<job-id>/` (gitignored).
2. Pivot long → wide per `serving_ahu` (or equipment slug) using `point_role` → FDD alias map from **`openfdd_ingest_contract`** (`outside_air_temp`→`oa_t`, `zone_temp`→`zn_t`, `discharge_air_temp`→`duct_t`, …).
3. Reject metadata-only files (e.g. `equipment_inventory.csv` with no `ts`) — use commissioning import instead.
4. **`openfdd_csv_import_preview`** on cleaned wide CSV(s) → **`openfdd_csv_import_plan`** with `timestamp`, `equipment_id`, `site_id`, FDD columns → preflight loop until `verdict: pass` → **`openfdd_csv_import_execute`** with `confirm: true` (optional `delete_staged_files: true`).
5. Optional env test: `OPENFDD_TADCO_IMPORT_DIR=/path/to/hvac_systems_CLEANED cargo test tadco_env_preflight -- --ignored` (operator sidecar only; not a customer name).

See [ingest contract (archive)](../docs/archive/agent/ingest-contract-v1.md) or [MCP docs](https://bbartling.github.io/open-fdd/mcp-agents/).

## Write tools (Phase 2)

Set **`OPENFDD_MCP_ALLOW_WRITES=1`** on the MCP server and pass **`confirm: true`** on each write tool call:

| Tool | Action |
|------|--------|
| `openfdd_csv_import_execute` | Save CSV session to Arrow/historian (preflight must pass) |
| `openfdd_model_commissioning_import` | Import commissioning bundle |
| `openfdd_rules_batch` | Run all active saved FDD SQL rules |
| `openfdd_fdd_rules_save` | Save SQL fault rule |
| `openfdd_fdd_rules_activate` | Activate saved rule |
| `openfdd_reports_from_fdd_sql_run` | PDF from SQL FDD run |
| `openfdd_integration_smoke` | Optional write steps when `confirm: true` |
| `openfdd_fdd_run` | Run ad-hoc DataFusion FDD SQL |
| `openfdd_model_assignments_save` | Persist Haystack assignments |
| `openfdd_reports_draft` | Create report draft |
| `openfdd_reports_patch` | Update report sections |
| `openfdd_reports_render_pdf` | Render PDF |

Read tools (preview, plan, preflight, contract, test-sql, fusion, historian query) do not require write gate.

## Haystack (Niagara nHaystack)

- URL pattern: `https://<station>/haystack` with **HTTP Basic** (`auth_mode=basic`) — **NOT SCRAM**
- Self-signed TLS: `tls_verify=false` in `workspace/haystack/local.nhaystack.toml`
- Credentials: `OPENFDD_HAYSTACK_USER` / `OPENFDD_HAYSTACK_PASS` (never commit)

## BACnet field reads

Use **commission** API (`OPENFDD_COMMISSION_BASE`, default `http://127.0.0.1:9091`) for OT Who-Is/reads — not bridge host-network.

On **fieldbus**, `POST /bacnet/whois` binds **`0.0.0.0`** + hosted BACnet/IP port (`whois_bind_port = 0` → server port, `SO_REUSEADDR`) so directed-broadcast I-Am is heard (#526). Unicast ReadProperty stays on ephemeral ports. Prefer fieldbus `:8081` for product discovery; commission/MCP companions for isolated debug.

Production BACnet throttling (agents): **300 s** default poll, **60 s** minimum, ~**30%** HVAC health points on cell sites — [`docs/operations/BACNET_OT_POLICY.md`](../docs/operations/BACNET_OT_POLICY.md). Independent OT debug: [`docs/mcp-agents/companion-rusty-bacnet-mcp.md`](../docs/mcp-agents/companion-rusty-bacnet-mcp.md) (read-only; does not replace fieldbus).

## Model (Haystack RDF)

Use `openfdd_model_sparql_catalog` then `openfdd_model_sparql` with a SELECT query. Assignments: `openfdd_model_assignments_save` with full points/bindings doc.

## FDD

- `openfdd_fdd_rules_list` — catalog
- `openfdd_fdd_rule_test_sql` — dry-run `{rule_id, sql, params}`
- `openfdd_fdd_run` — execute ad-hoc SQL (write gate)

## Safety

Never log tokens or Haystack passwords. Do not delete `workspace/data` without operator approval.

If a suspected vulnerability is discovered, do **not** create a public GitHub issue/discussion or paste exploit evidence into public chat. Use GitHub Private Vulnerability Reporting at `https://github.com/bbartling/open-fdd/security/advisories/new`. Include affected component/version, reproduction steps, proof of impact, and redacted evidence. Never disclose JWTs, BAS credentials, registry tokens, private hostnames, or OT details. See [`SECURITY.md`](../SECURITY.md).

## Equipment typing

During package cleaning/modeling, stamp generic `equipType` / `equipment_type` metadata. The product persists and prefers that stamp; folder/id inference is fallback. Empty Overview families on opaque ids are a package-modeling signal, not a reason to add site-specific Rust heuristics.
