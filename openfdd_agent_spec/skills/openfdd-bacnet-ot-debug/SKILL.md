---
name: openfdd-bacnet-ot-debug
description: >-
  historical/non-executable. BACnet Who-Is, fieldbus, MS/TP, and MQTTS debug
  are not the 4.0 portal path. Product ingest is the Normal Framework portal
  API and CSV. Triggers on: BACnet, Who-Is, fieldbus, rusty-bacnet, MQTTS ingest.
---

# BACnet OT debug — historical/non-executable

`architecture_epoch: portal-timescale-v1`. This skill is not an instruction to run fieldbus or a broker.

Product ingest is the Normal Framework portal API and CSV. Timescale is the historian. Railway services are central and web.

`openfdd-mcp` talks to central REST. It does not list `openfdd_bacnet_whois` or `openfdd_bacnet_read`. Those calls return `ot_transport_retired`.

Empty RCx or FDD plots are missing roles on the package or portal inventory. Map them with [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md). Do not add a poll catalog to fill a chart.

Retired wire commands, image pins, and the public Railway ZAP order are `historical/non-executable` in [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../../../docs/archive/ai-agent/historical-3.5-ot-ops.md). The container snapshot is [`archive/ot-edge/`](../../../archive/ot-edge/). `openfdd_stack_up.sh` refuses `standalone`, `edge`, and `react-ot`.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-package-mapping`](../openfdd-package-mapping/SKILL.md) — roles for an empty chart
- [`openfdd-railway-cli`](../openfdd-railway-cli/SKILL.md) — central and web re-pin
- [`openfdd-stack-ghcr`](../openfdd-stack-ghcr/SKILL.md) — portal image pull
