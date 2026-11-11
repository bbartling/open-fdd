---
title: Home
nav_order: 1
permalink: /
---

# Open-FDD

Open-FDD is a fault-detection and retro-commissioning app for the Normal Framework (NF). It reads NF's modeled
equipment, points, and history and writes its results as ordinary NF points.

## Editions

| Edition | Use |
|---|---|
| Full | SQL fault rules, charts, export, RDF/SPARQL, and scheduled FDD and weather hooks |
| Lite | Dashboard, charts, export, RDF, and weather for smaller hosts, without FDD or Timescale |

## Guides

- [Install the NF app](install.html) covers Full and Lite, supported install routes, hooks, and upgrades.
- [Modeling](modeling.html) explains how to tag equipment and points so roles bind.
- [Writing SQL rules](sql-rules.html) and [writing pandas rules](pandas-rules.html).
- [API reference](fdd-data-access.html) covers point metadata, results, and history.
- [FDD rule catalog](fdd-rules.html) lists production rules and defaults.
- [Charts](charts.html), [export](export.html), and [RDF/SPARQL](rdf-sparql.html).
- [Plot spec](plot-spec.html) is the shared description of which series and fault strips a plot shows.

Find the source and full release history on [Open-FDD on GitHub](https://github.com/bbartling/open-fdd) and its
[releases](https://github.com/bbartling/open-fdd/releases).
