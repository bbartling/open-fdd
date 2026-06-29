# Open-FDD MCP server instructions

Read-first MCP sidecar for the Rust edge bridge. Requires JWT via `OPENFDD_MCP_TOKEN` or unauthenticated `/api/health` only.

## Write tools (Phase 2)

Set **`OPENFDD_MCP_ALLOW_WRITES=1`** on the MCP server and pass **`confirm: true`** on each write tool call:

| Tool | Action |
|------|--------|
| `openfdd_csv_import_execute` | Save CSV session to Arrow/historian |
| `openfdd_fdd_run` | Run ad-hoc DataFusion FDD SQL |
| `openfdd_model_assignments_save` | Persist Haystack assignments |
| `openfdd_reports_draft` | Create report draft |
| `openfdd_reports_patch` | Update report sections |
| `openfdd_reports_render_pdf` | Render PDF |

Read tools (preview, plan, test-sql, fusion, historian query) do not require write gate.

## CSV agent workflow

1. **`openfdd_csv_import_preview`** — `files: [{filename, path}]` from host (e.g. Lake Geneva folder) or `content_base64` for small files. Optional `session_id` to append.
2. **`openfdd_csv_import_plan`** — `session_id` + `plan` (mode `join`, school files + weather, `floor_hour`).
3. **`openfdd_csv_fusion_preview`** — review merged grid.
4. **`openfdd_csv_import_execute`** — `confirm: true` + write gate → Arrow store.
5. **`openfdd_timeseries_series`** / **`openfdd_historian_query`** — plot/analytics inputs.
6. **`openfdd_reports_draft`** → **`openfdd_reports_patch`** → **`openfdd_reports_render_pdf`**.

Large uploads use multipart automatically when total size exceeds ~900KB.

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
