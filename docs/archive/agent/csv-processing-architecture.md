# CSV processing: inside vs outside Open-FDD

## Recommendation (lots of files, many jobs)

Use a **hybrid** split optimized for volume and auditability:

| Phase | Where | Why |
|-------|--------|-----|
| **Upload + catalog** | **Inside** Open-FDD | JWT, sessions, Arrow store, historian, model bindings — single source of truth |
| **Heavy transform / ETL** | **Agent toolshed** (outside runtime) | Codex writes scripts to `workspace/agent-toolshed/`; edge stores results only |
| **Merge / validate / commit** | **Inside** via MCP | `openfdd_csv_*` tools — preview, plan, row counts, save to Arrow |
| **FDD equations** | **Inside** model + SQL FDD | Assignments and DataFusion rules run on committed historian data |

Agents should **not** keep large merged CSVs only in chat memory. Flow:

1. Operator drops files on CSV tab (or MCP upload).
2. Agent profiles via MCP `openfdd_csv_import_*` / sessions API.
3. Scratch transforms in `workspace/agent-toolshed/<job-id>/` (gitignored).
4. Validate row counts and schema via MCP preview.
5. Save to Arrow store → model assignments → FDD rules.

For **many parallel jobs**, each job gets a `session_id` + toolshed subdirectory; the edge queue is the session list in `workspace/` — not the agent process.

## When to stay fully inside

- Single-site commissioning, &lt;10 files, operator-driven merge on wiresheet.
- Production edge with no Codex — use UT3/MCP API only.

## When to lean outside

- Research-scale batches (dozens of school-year kW files + weather).
- Custom Python/R one-offs — toolshed scripts call edge REST when ready to commit.

See [model-routing.md](model-routing.md) for which agent handles CSV vs FDD vs review work.
