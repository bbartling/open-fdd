# Open-FDD MCP server instructions

Read-first MCP sidecar for the Rust edge bridge. Requires JWT via `OPENFDD_MCP_TOKEN` or unauthenticated `/api/health` only.

## Login / credentials (agents)

MCP runs on the **host** and resolves passwords locally — never from bcrypt hashes in `auth.env.local`.

| Source | Path / env |
|--------|------------|
| One-time handoff | `workspace/bootstrap_credentials.once.txt` — lines `integrator: …`, `agent: …` |
| Env override | `OPENFDD_INTEGRATOR_PASSWORD`, `OPENFDD_AGENT_PASSWORD` |
| Shell helper | `scripts/openfdd_auth_lib.sh` → `openfdd_auth_login_token` |

**MCP tools:**

- `openfdd_auth_credentials_hint` — paths and roles (no secrets)
- `openfdd_auth_login` — `{ "role": "integrator" }` → JWT for `OPENFDD_MCP_TOKEN`

Works with **Cursor, Claude Desktop, Codex CLI, OpenClaw**, or any MCP host. Open-FDD does **not** ship a built-in chatbot — connect external agents through this stdio server or JWT REST.

## Model + FDD wiresheet

After `openfdd_model_assignments_save` (with `confirm: true`), the **FDD wiresheet** on Model → **FDD wiresheet** tab auto-syncs (`graph:live-fdd-validation`). Or call `openfdd_fdd_wires_sync` / `openfdd_fdd_wires_propose`.

## CSV agent workflow (agent-first ingest)

1. **`openfdd_ingest_contract`** — read historian_wide_csv + commissioning mold before cleaning.
2. **Agent sandbox** — reshape CSVs in `workspace/agent-toolshed/<job-id>/` (gitignored; never commit Python/CSV to repo).
3. **`openfdd_csv_import_preview`** — `files: [{filename, path}]` from host or `content_base64`.
4. **`openfdd_csv_import_plan`** — `session_id` + `plan` (mode, files, timezone, value_columns).
5. **`openfdd_csv_import_preflight`** — **required**; loop until `verdict: "pass"` (read `validation.checks` + `agent_hints`).
6. **`openfdd_csv_import_execute`** — `confirm: true` + write gate → Arrow + historian (fail-closed unless preflight pass).
7. Optional **`openfdd_model_commissioning_import`** — sites/equipment/points/assignments/rules bundle.
8. **`openfdd_fdd_rule_test_sql`** → **`openfdd_rules_batch`** (not `openfdd_fdd_run` for saved rules).
9. **`openfdd_reports_from_fdd_sql_run`** — PDF with `download_url`.

Composite: **`openfdd_integration_smoke`** — `{ import_dir?, session_id?, confirm?, run_fdd?, run_report? }`.

Helper script (bash only): `scripts/openfdd_csv_preflight.sh <session_id>`.

### Liberty Center / Niagara long-format CSV (TADCO)

Field exports such as `hvac_systems_CLEANED/` are **long-format** Niagara grids — not historian-wide shape. Agent must pivot before preflight pass.

1. Copy raw files to `workspace/agent-toolshed/<job-id>/` (gitignored).
2. Pivot long → wide per `serving_ahu` (or equipment slug) using `point_role` → FDD alias map from **`openfdd_ingest_contract`** (`outside_air_temp`→`oa_t`, `zone_temp`→`zn_t`, `discharge_air_temp`→`duct_t`, …).
3. Reject metadata-only files (e.g. `equipment_inventory.csv` with no `ts`) — use commissioning import instead.
4. **`openfdd_csv_import_preview`** on cleaned wide CSV(s) → **`openfdd_csv_import_plan`** with `timestamp`, `equipment_id`, `site_id`, FDD columns → preflight loop until `verdict: pass` → **`openfdd_csv_import_execute`** with `confirm: true` (optional `delete_staged_files: true`).
5. Optional env test: `OPENFDD_TADCO_IMPORT_DIR=/path/to/hvac_systems_CLEANED cargo test tadco_env_preflight -- --ignored`.

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

## Model (Haystack RDF)

Use `openfdd_model_sparql_catalog` then `openfdd_model_sparql` with a SELECT query. Assignments: `openfdd_model_assignments_save` with full points/bindings doc.

## FDD

- `openfdd_fdd_rules_list` — catalog
- `openfdd_fdd_rule_test_sql` — dry-run `{rule_id, sql, params}`
- `openfdd_fdd_run` — execute ad-hoc SQL (write gate)

## Safety

Never log tokens or Haystack passwords. Do not delete `workspace/data` without operator approval.
