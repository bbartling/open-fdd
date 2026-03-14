# Open-FDD

![CI](https://github.com/bbartling/open-fdd/actions/workflows/ci.yml/badge.svg?branch=master)
![MIT License](https://img.shields.io/badge/license-MIT-green.svg)
![Development Status](https://img.shields.io/badge/status-3%20--%20Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![BACnet](https://img.shields.io/badge/Protocol-BACnet-003366)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-compatible-FDB515?logo=timescale&logoColor=black)
![Grafana](https://img.shields.io/badge/Grafana-supported-F46800?logo=grafana&logoColor=white)
![PyPI](https://img.shields.io/pypi/v/open-fdd?color=blue&label=pypi%20version) — *PyPI package is legacy (FD equations only; no AFDD framework) and is no longer supported. Use this repo.*
[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2.svg?logo=discord&logoColor=white)](https://discord.gg/Ta48yQF8fC)

<div align="center">

![open-fdd logo](image.png)

</div>

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `config/data_model.ttl`.

---


## Quick Start — Open-FDD AFDD Platform

Open-FDD uses Docker and Docker Compose to orchestrate and manage all platform services within a unified containerized environment. The bootstrap script (`./scripts/bootstrap.sh`) is **Linux only** (tested on Ubuntu Server and Linux Mint, x86; should work on ARM but is untested). Windows is not supported.

### 🚀 Platform Deployment (Docker)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

This will start the full AFDD edge stack locally. The stack includes Grafana, TimescaleDB, and a Python rules engine built on pandas for time-series analytics; the default protocol is **BACnet** for commercial building automation data. Future releases will add other data sources such as REST/API and Modbus.


### Development: run unit tests

No Docker needed for the test suite. From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

- **`.[dev]`** installs pytest, black, aiohttp, and platform deps so the full suite (open_fdd + HA integration tests) runs.
- Test paths are set in `pyproject.toml` (`open_fdd/tests`, `stack/ha_integration/tests`). Run `pytest` with no path to use them.
- Style and workflow: [docs/contributing.md](docs/contributing.md).


---


## AI Assisted Data Modeling


In the Open-FDD frontend, there is a feature to export the RDF data model to JSON for further enhancement with the Brick ontology and upload it to an LLM for AI-assisted data modeling. Copy the prompt below, upload the YAML files defined for the job, and the LLM should know what to do.

Use the export API and an LLM (e.g. ChatGPT) to tag BACnet discovery points with Brick types, rule inputs, and equipment; then import the tagged JSON so the platform creates equipment by name and links points without pasting UUIDs. For full workflow and **deterministic mapping** (repeatable, rules-style tagging), see [docs/modeling/ai_assisted_tagging.md](docs/modeling/ai_assisted_tagging.md) and [docs/modeling/llm_mapping_template.yaml](docs/modeling/llm_mapping_template.yaml). For a **one-shot LLM workflow** (upload prompt + export JSON + optional rules YAML, validate with schema so backend accepts it, then import and run FDD/tests), see [docs/modeling/llm_workflow.md](docs/modeling/llm_workflow.md).

The engineer should chat with the LLM about the task at hand after first understanding the HVAC system from a systems perspective. The LLM can then provide additional metadata, such as Brick classes for point names, along with feeds and fed-by relationships. The final output JSON file is then imported back into Open-FDD, where the backend parses it into a completed data model.

A slightly more polished version for docs or README text:

In the Open-FDD frontend, there is a feature to export the RDF data model to JSON for further enhancement using the Brick ontology and an LLM for AI-assisted data modeling. Copy the prompt below and upload the YAML files defined for the task, and the LLM should understand how to proceed.

After reviewing the HVAC system from a systems perspective, the engineer can chat with the LLM about the modeling task. The LLM can then generate additional metadata, including Brick classes for point names and feeds/fed-by relationships. The final output JSON file is imported back into Open-FDD, where the backend parses it into a completed data model.


```text
I use Open-FDD. Please help me model my mechanical system’s feeds and fed-by relationships. If not enough data is available, please ask. Do not infer or assume relationships from probability—only the engineer knows the actual mechanical relationships for the HVAC.

I will paste JSON from GET /data-model/export (optionally filtered with ?site_id=YourSiteName).

Your job is to convert that export into CLEAN Open-FDD import JSON.

Return ONLY valid JSON with exactly two top-level keys:

{
  "points": [...],
  "equipment": [...]
}

Ensure all devices in the RDF are assigned to the site at hand even if they are not used in a data model or fault rule.

---------------------------------------------------------------------

POINT RULES

For each point:

Preserve all existing fields from the export including:

- point_id
- bacnet_device_id
- object_identifier
- object_name
- external_id
- site_id
- site_name
- equipment_id (preserve but DO NOT use for relationships)

Then add or fill these fields:

- brick_type
- rule_input
- polling
- unit
- equipment_name
- equipment_type

Equipment must be referenced by NAME only.

Set equipment_type to the Brick equipment class (e.g. Air_Handling_Unit, Variable_Air_Volume_Box) so that the Open-FDD Data Model Testing "Summarize your HVAC" buttons (AHUs, VAV boxes, etc.) show results. If omitted, equipment is created as generic Equipment.

Example:

"equipment_name": "AHU-1",
"equipment_type": "Air_Handling_Unit"

Never use equipment UUIDs for relationships.

---------------------------------------------------------------------

SITE ID

Use the exact site_id from the export rows.

Do not invent or modify site_id values.

If site_id is null in the export, leave it null.

---------------------------------------------------------------------

EQUIPMENT ARRAY

Return an "equipment" array describing system relationships.

Each item must include:

- equipment_name
- site_id

Include equipment_type (Brick equipment class) so that "Summarize your HVAC" (AHUs, VAV boxes, VAVs per AHU, etc.) shows correct counts. Use e.g. Air_Handling_Unit, Variable_Air_Volume_Box, Variable_Air_Volume_Box_With_Reheat, HVAC_Zone, Chiller, Boiler, Cooling_Tower, Weather_Service. If omitted, equipment is created as Equipment.

Example:

{
  "equipment_name": "AHU-5",
  "equipment_type": "Air_Handling_Unit",
  "site_id": "<site_id>",
  "feeds": ["VAV-1"]
}

If a VAV is served by an AHU:

AHU:

"feeds": ["VAV-1"]

VAV:

"fed_by": ["AHU-5"]

Prefer:

"feeds"
"fed_by"

Only use:

"feeds_equipment_id"
"fed_by_equipment_id"

if required by the source export.

---------------------------------------------------------------------

EQUIPMENT TYPE (Brick summaries)

For the Data Model Testing page "Summarize your HVAC" buttons to list AHUs, VAV boxes, etc., equipment must have the correct Brick class. Set equipment_type on points and in the equipment array to the Brick class name (no "brick:" prefix), e.g.:

- Air_Handling_Unit — AHUs
- Variable_Air_Volume_Box or Variable_Air_Volume_Box_With_Reheat — VAV boxes
- HVAC_Zone — zones
- Chiller, Cooling_Tower, Boiler — central plant
- Weather_Service — weather (optional)

Infer from point names and BACnet device grouping: e.g. points SA-T, MA-T, RA-T, SF-O, CLG-O on one device are typically one AHU; ZoneTemp, VAVFlow, VAVDamperCmd on another device are typically one VAV box. Assign equipment_name and equipment_type so that after import, "AHUs" and "VAV boxes" (and "VAVs per AHU" if you set feeds/fed_by) return counts.

---------------------------------------------------------------------

BRICK TYPES

Use appropriate Brick classes when possible.

Examples:

brick:Supply_Air_Temperature_Sensor  
brick:Return_Air_Temperature_Sensor  
brick:Mixed_Air_Temperature_Sensor  
brick:Outside_Air_Temperature_Sensor  
brick:Zone_Air_Temperature_Sensor  
brick:Supply_Fan_Status  
brick:Supply_Fan_Command  
brick:Cooling_Valve_Command  
brick:Heating_Valve_Command  
brick:Damper_Position_Command  
brick:Discharge_Air_Flow_Sensor  
brick:Discharge_Air_Flow_Setpoint  
brick:Supply_Air_Temperature_Setpoint  

If a point cannot be confidently mapped:

"brick_type": null

---------------------------------------------------------------------

RULE INPUTS

Set rule_input to short reusable slugs.

Examples:

ahu_sat  
ahu_sat_sp  
rat  
mat  
oat  
zone_temp  
sf_status  
sf_cmd  
clg_cmd  
htg_cmd  
damper_cmd  
airflow  
airflow_sp  

If unknown:

rule_input = null

---------------------------------------------------------------------

POLLING

Set polling=true for points defined in the yaml files for FD rules and typical HVAC RCx data reporting:

temperatures  
humidity  
flow  
pressures  
fan status  
commands  
setpoints  
valves  
dampers  
power

Set polling=false for:

network ports  
metadata objects  
housekeeping points
vav box air balancing parameters
pid settings
bacnet device names
trend logs

---------------------------------------------------------------------

UNITS

Use consistent engineering units.

Examples:

degF or °F
%
cfm
mph
W/m²
0/1 (binary)

If unknown:

unit = null

---------------------------------------------------------------------

DUPLICATES

Do not rename external_id values.

If duplicates exist, keep them unchanged.

Open-FDD import logic uses:

(site_id + external_id)

with last row winning.

---------------------------------------------------------------------

OUTPUT

Return full JSON only.

No markdown  
No explanation  
No extra keys

Make the output generic and reusable for any Open-FDD export.

Preserve fields first, enrich second.
Leave uncertain values as null rather than guessing.

Chat With the Engineer asking if this is complete? Verify feeds or fed replationships. And if anything else is needed.
```

The final step is for the engineer to perform robust SPARQL query testing to verify that the data model returns the exact expected responses needed to summarize the HVAC system. For example, if the site contains a VAV AHU system with chiller-based cooling, the engineer should test queries that validate the connected relationships in the model, including those needed to support control algorithms and fault detection logic.

There is a SPARQL cookbook in the documentation that can be used for this purpose. These tests should confirm that the data model returns the expected feed and fed-by relationships for the HVAC system. From there, additional SPARQL queries can be developed for algorithm-specific needs. For example, a Guideline 36 duct static pressure reset sequence may require querying for all BACnet devices and point addresses associated with VAV boxes served by a given AHU, including damper positions or commands, airflow sensor values and setpoints, and the AHU duct static pressure sensor and static pressure setpoint.

Overall, SPARQL testing should be used by the engineer to validate that the data model fully supports the optimization algorithms and fault rules planned for the site.


## The open-fdd Pyramid


If OpenFDD nails the ontology, the project will be a huge success: an open-source knowledge graph for buildings. Everything else is just a nice add-on.

![Open-FDD system pyramid](https://raw.githubusercontent.com/bbartling/open-fdd/master/OpenFDD_system_pyramid.png)

---

## Online Documentation

[📖 Docs](https://bbartling.github.io/open-fdd/) — For a copy-paste guide to run Open-FDD on Linux hardware.

---


## Dependencies

[pandas](https://github.com/pandas-dev/pandas) · [PyYAML](https://github.com/yaml/pyyaml) · [FastAPI](https://fastapi.tiangolo.com/)  

Optional: [rdflib](https://github.com/RDFLib/rdflib) (Brick TTL), [matplotlib](https://github.com/matplotlib/matplotlib) (viz)

---

## Contributing

Contributions welcome — especially bug reports, rule recipes (see the [expression rule cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook)), BACnet integration tests, and documentation. See [docs/contributing.md](docs/contributing.md) for how to get started.

```bash
~/open-fdd$ bash scripts/bootstrap.sh --test
```

> **NOTE:** Please contribute on a new branch. Any pushes to the `master` branch, including pull requests opened from `master`, will be rejected.


---

## License

MIT