---
title: AI agents & skills
parent: PyPI agent tools
nav_order: 4
permalink: /ecm/agent-context.html
---

# How Open-FDD AI agents help humans

Open-FDD does **not** ship an embedded chatbot. External agents (Cursor, Codex, Claude Desktop, OpenClaw, MCP hosts) connect with **JWT REST** and optional **`openfdd-mcp` stdio**.

## What agents are for

| Human need | Agent capability |
|------------|------------------|
| Commission a site package | Map Haystack / CSV columns → SQL roles; stamp `equipType`; prove Overview/RCx/FDD nonempty |
| Run / tune FDD | `POST /api/fdd/run`, Lab tuners, series overlays — DataFusion on central |
| ECM / savings workbook | Fill **input cells only** via `open_fdd.ecm_engineering.ECMJob`; Excel keeps formulas |
| EnergyPlus honesty | Attach twin compare; label FITTED / BALLPARK / NO_EP — never greenwash |
| OT debug (read-first) | BACnet Who-Is / RP via companion MCP — **no writes** without explicit human approval |
| Hub ops | Railway CLI pin, GHCR newest-by-created, stress closeout scripts |

**Rules of the road:** never invent required inputs; never print secrets; never ActiveScan production OT from Mint; Kali owns ZAP/PEN when used.

## Skills (read these)

| Skill | Path |
|-------|------|
| ECM engineering | [`openfdd-ecm-engineering/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md) |
| Package mapping | [`openfdd-package-mapping/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-package-mapping/SKILL.md) |
| Data modeling | [`data-modeling/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/data-modeling/SKILL.md) |
| SQL FDD | [`openfdd-sql-fdd/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-sql-fdd/SKILL.md) |
| Cookbook parity | [`openfdd-cookbook-parity/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-cookbook-parity/SKILL.md) |
| PyPI oracle | [`openfdd-pypi-oracle/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-pypi-oracle/SKILL.md) |
| Stack / GHCR | [`openfdd-stack-ghcr/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-stack-ghcr/SKILL.md) |
| Railway CLI | [`openfdd-railway-cli/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md) |
| Stress closeout | [`openfdd-stress-closeout/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-stress-closeout/SKILL.md) |
| BACnet OT debug | [`openfdd-bacnet-ot-debug/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-bacnet-ot-debug/SKILL.md) |
| React SPA | [`openfdd-react-spa/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md) |
| RCx/FDD plot → poll | [`openfdd-rcx-fdd-plot-poll/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-rcx-fdd-plot-poll/SKILL.md) |
| Multi-tenant / Kali security | [`openfdd-mt-security/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-mt-security/SKILL.md) |
| Typst RCx report | [`openfdd-typst-rcx-report/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-typst-rcx-report/SKILL.md) |

Offline single-system or building-folder AHU PDF sources: `open-fdd-anomaly report <folder> --out <dir> --month YYYY-MM`. Web OAT from a mapped column, `--web-oat` CSV, or `--web-oat fetch`. Economizer closer is `economizer_delta_scatter` viewport `bottom_left` (**x = OAT − RAT**, **y = MAT − RAT**). Do not plot OAT−MAT vs RAT−MAT. No histograms. That pack is not the BUILDING_100 Overview mirror.
| Architecture | [`openfdd-architecture/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-architecture/SKILL.md) |
| Milestone A PR | [`openfdd-milestone-a-pr/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-milestone-a-pr/SKILL.md) |

## ECM agent rules (summary)

1. Prefer BAS / meter / TAB / nameplate evidence — never invent required inputs.  
2. Never overwrite Excel formula cells.  
3. Python `calculate(...)` is a referee, not hidden sheet math.  
4. Preserve provenance; do not stack interacting ECM savings blindly.  
5. Prefer the versioned **`ecm_context_v1`** envelope (`open_fdd.ecm_engineering.context_envelope`) for agent context: assets with distinct command/power points, tariff gaps → monetary UNAVAILABLE, readiness `screening` \| `validated` \| `submission_ready` (human review required for the last).
6. Prefer **EQ-VOCAB** records + **`adapt_model_to_calculator`** when feeding nameplate capacities into fan/schedule/kW-ton screens — never invent annual hours from capacity alone. See [Model → ECM calculations](model-to-calculations.html).  
6. Combined schedule + fan reset: use `combine_schedule_then_fan_reset` (reset on **remaining** hours) — never sum standalone savings for the same end-use.

Executable plan: [`.cursor/plans/ecm_context_hardening.plan.md`](https://github.com/bbartling/open-fdd/blob/master/.cursor/plans/ecm_context_hardening.plan.md).

Full calc catalog: [Engineering calcs](engineering-calcs.html).

## Related

- [Purpose — Excel + EnergyPlus](purpose-excel-energyplus.html)  
- [Install & overview](overview.html)  
- MCP: [`docs/mcp-agents/`](https://github.com/bbartling/open-fdd/tree/master/docs/mcp-agents) · [`AGENTS.md`](https://github.com/bbartling/open-fdd/blob/master/AGENTS.md)
