# `scripts/`

| Script | Purpose |
|--------|---------|
| **`build_docs_pdf.py`** | Maintainer helper to combine Markdown docs and build `pdf/open-fdd-docs.pdf` (optional Pandoc / WeasyPrint). Also writes `pdf/open-fdd-docs.txt` with `--no-pdf`. |

Retired monolith launchers (`start-local.*`, `build_mcp_rag_index.py`, `linux-lan/`) were removed in favor of `skills/` and `packages/openfdd-agent-shell`.

From the repo root:

```bash
python scripts/build_docs_pdf.py --no-pdf
```
