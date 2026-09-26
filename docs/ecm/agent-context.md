---
title: AI agents & skills
parent: PyPI agent tools
nav_order: 4
permalink: /ecm/agent-context.html
---

# How Open-FDD AI agents help humans

Open-FDD does **not** ship an embedded chatbot. Any AI agent that can read markdown skills and run the PyPI CLI can use this package (Cursor, Claude, Codex, OpenClaw, Hermes, Grok Bot, or another MCP host). `openfdd_agent_spec/skills/` is the only authoring tree ([index](https://github.com/bbartling/open-fdd/tree/master/openfdd_agent_spec/skills)). Do not invent a parallel skill under `.cursor/skills/` or another vendor directory. `./scripts/openfdd_install_agent_skills.sh --sync` (add `--user` for home directories) is the sync into Cursor, Claude, Codex, OpenClaw, Hermes, and Grok. Live stacks still use **JWT REST** and optional **`openfdd-mcp` stdio**. The CSV/API-agnostic PDF command is `open-fdd-anomaly report ... --compile`.

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
| Architecture | [`openfdd-architecture/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-architecture/SKILL.md) |
| Milestone A PR | [`openfdd-milestone-a-pr/SKILL.md`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-milestone-a-pr/SKILL.md) |

Offline RCx PDFs are host-independent. The only shipped PDF command is `open-fdd-anomaly report <folder> --out <dir> --month YYYY-MM --compile` (no `build_april_report.py` or other out-of-tree runner). It reads a device folder (`history_wide.csv` + `column_map.json`). The same template accepts an Open-FDD central reader or a future vendor reader (`open_fdd.reporting.report_template`). Order is sensor-check bullets, then a plain anomaly pass/fail list, then role-selected RCx figures, then fault plots. `--week 2026-04-06` pins the April RCx window through 2026-04-12. Web OAT (`web_oa_t` reindexed onto the BAS clock, then `prefer_web_oat`) drives the supply-air scatter and `bas_vs_web_oat_overlay`. Economizer closer is `economizer_delta_scatter` viewport `bottom_left` (**x = OAT − RAT**, **y = MAT − RAT**) via `build_economizer_delta_points` (`economizer_delta_frame` is the same function). `vav_ahu` and `cv_ahu` share the air-side figures (`unitVentilator` / `uv` → `cv_ahu`). `single_zone`, `chiller`, `boiler`, `heat_pump`, `vav_box`, `fan_coil`, `geothermal_field`, and `data_hall` are registered stubs. Agents fill `ai_comments.json` slots; empty slots stay out of the PDF. No histograms and no re-run footer. `--compile` writes `report.pdf` when `typst` is on `PATH`. That pack does not read `/home/ben/building100_rcx_report` and is not the BUILDING_100 Overview mirror.

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
