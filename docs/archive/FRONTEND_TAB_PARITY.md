# Frontend Tab Parity

This document maps the old Open-FDD UI areas to the Rust-only UI.

| Old/Open-FDD area | Rust tab | Backend route |
| --- | --- | --- |
| Open-FDD dashboard | Open-FDD | `/api/building/checkin` |
| Bridge API | Bridge API | `/api/bridge/status` |
| BACnet commission | BACnet Commission | `/api/bacnet/commission/status` |
| BACnet poll | BACnet Poll | `/api/bacnet/poll/status` |
| Niagara | Haystack Model | `/api/haystack/read` |
| Data model | Haystack Model | `/api/model/haystack`, `/api/model/sparql` |
| Rule Lab | Rule Lab | `/api/rules/save` |
| FDD | DataFusion FDD | `/api/fdd/run` |
| Modbus | Modbus | `/api/modbus/points` |
| JSON API | JSON API | `/api/json-api/sources` |
| Reports | Reports | `/api/reports/rcx/generate` |
| Agent/API | AI API | `/api/agent/tools` |
| Stack health | Ops | `/api/health/stack` |

## Converted or removed

- Niagara WebSocket tab is converted to Project Haystack read/nav/ops.
- Data model is Haystack + SPARQL over RDF.
- FDD is DataFusion SQL only.
- CDL algorithms get a dedicated tab.
- MCP/RAG and Ollama are deferred.
- No Python, no PyArrow, no pandas.

## Assignment tab

The `Assignments` tab is the glue layer.

It shows:

- Haystack point IDs
- driver bindings
- external refs
- Arrow storage refs
- DataFusion fault equation bindings
- CDL algorithm I/O bindings

No algorithm or fault equation should care which protocol produced the value.
