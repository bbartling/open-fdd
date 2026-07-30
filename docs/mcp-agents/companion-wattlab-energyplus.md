---
title: Companion — WattLab + EnergyPlus-MCP
parent: MCP Agents
nav_order: 5
---

# Companion: WattLab tools + EnergyPlus-MCP

**Read this when the task involves Twin calibrate, Fuel bills, ECM Excel, or IDF/EnergyPlus.**  
`openfdd-mcp` alone is **FDD / sites / historian** — it does **not** perform EnergyPlus IDF surgery.

## Three surfaces (do not collapse)

| Surface | Role | How agents reach it |
|---------|------|---------------------|
| **openfdd-mcp** | JWT → central REST: health, CSV ingest, FDD SQL, Haystack, reports | Cursor `mcp.json` `openfdd` server; `mcp/INSTRUCTIONS.md` |
| **EnergyPlus-MCP** | LBNL ~35 tools in `wattlab_workspace/third_party/EnergyPlus-MCP` → image `energyplus-mcp-dev` | Separate MCP server **or** `wattlab energyplus-ensure` + `wattlab mcp-exec` |
| **WattLab `tools/` + skills** | CLIs, playbooks, full-parity Excel builders, Cursor skills | Files under `~/wattlab_workspace/tools/`; `~/.cursor/skills/wattlab-*` |

Hard rule: **never** embed EnergyPlus IDF surgery inside `openfdd-mcp`. Always point Twin/ECM work at EnergyPlus-MCP / vibe20 wrappers.

## Golden loop (Liberty Twin → ECM)

```text
A. Context (every Twin/ECM session)
   1. ~/wattlab_workspace/WORKSPACE.md
   2. tools/AGENT_CONTEXT.md + tools/BEST_PRACTICES_EPLUS_MCP_ECM.md
   3. reports/BUG_REPORT.md (OFDD-* / BUG-ECM-*)
   4. Skills: wattlab-energyplus-mcp, wattlab-twin-calibrate-dial,
      wattlab-agent-driven-ecm-excel

B. FDD / sites / historian  →  openfdd-mcp (or JWT REST)
C. Twin / IDF / simulate     →  EnergyPlus-MCP or vibe20 mcp-exec
   docker exec vibe20 wattlab energyplus-ensure
   docker exec vibe20 wattlab mcp-exec -- <tool> …
D. ECM Excel / Compare       →  vibe20 + tools/ scripts
   python /data/tools/build_full_parity_ecm_workbook_v2.py
   Preferred book: reports/notebooks/full_parity_ecm/ECM_FULL_PARITY.xlsx
```

## Paths

| Host | In vibe20 / UI container |
|------|--------------------------|
| `~/wattlab_workspace` | `/data` |
| `…/third_party/EnergyPlus-MCP` | `/data/third_party/EnergyPlus-MCP` |
| `…/tools/` | `/data/tools/` |
| `…/reports/notebooks/full_parity_ecm/ECM_FULL_PARITY.xlsx` | same under `/data/reports/…` |

## Preferred ECM workbook (SoT)

- **Preferred:** `ECM_FULL_PARITY.xlsx` via `build_full_parity_ecm_workbook_v2.py`
- Studio merge: `reports/ecm_full_parity_compare.json` with top-level `rows` + `annual_usd` (BUG-ECM-015)
- Do **not** treat matched-hours / `ECM_EPLUS_MATCHED_HOURS.xlsx` as the product SoT

## Cursor dual-MCP snippet

Wire **both** servers. openfdd-only = FDD-blind-to-Twin.

```json
{
  "mcpServers": {
    "openfdd": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "ghcr.io/bbartling/openfdd-mcp:nightly"]
    },
    "energyplus": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/path/to/wattlab_workspace:/data",
        "energyplus-mcp-dev"
      ]
    }
  }
}
```

See also: [mcp.md](mcp.md), [cursor-openclaw.md](cursor-openclaw.md), root `mcp/INSTRUCTIONS.md`.
