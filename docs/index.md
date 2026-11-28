---
title: Home
nav_order: 1
nav_exclude: true
permalink: /
---

# Open-FDD

Open-FDD is a fault-detection and retro-commissioning app for the [Normal Framework](https://docs.normal.dev/) (NF). It reads NF's
modeled equipment, points and history, runs SQL fault rules in SI units, and writes results as ordinary NF points.

| Section | What is in it |
|---|---|
| [Rules](rules/) | SQL and pandas rule cookbooks with units per rule, using the SQL rules outside Open-FDD, parity |
| [Testing and parity](testing-parity.html) | FDD three-way engines and workflows; RDF closure, Shifty and the rdflib / Node SPARQL check |
| [Data model](modeling.html) | 223P roles, the Haystack overlay, SI units, RDF and SPARQL |
| [DuckDB vs Timescale](editions.html) | The two storage backends, charts, the [UI guide](ui-guide.html) and CSV export |
| [Normal Framework](normal-framework.html) | Install, upgrade, security and the API, linking to the NF docs |
| [Legacy](legacy.html) | Unsupported earlier deployments |
| [PyPI agent tools](pypi-agent-tools.html) | Every Python tool on PyPI: rules, NF and SPARQL clients, analytics, anomaly, ML, reports, ECM / ROI |

Source and release history: [GitHub](https://github.com/bbartling/open-fdd) and
[releases](https://github.com/bbartling/open-fdd/releases).
