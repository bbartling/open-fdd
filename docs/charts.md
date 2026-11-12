---
title: Charts
nav_order: 12
---

# Charts

Open-FDD has three chart surfaces. **Charts** plots selected point histories. **RCx** offers registered views for
equipment and sites. **FDD** plots rule results and sensor history.

Every chart surface (Overview, Charts, Points, FDD, RCx and the one-chart window) opens on the **last 7 days** by default.
Choose 1 hour, 24 hours, 1 week, or All, or set a custom start and end. The selected range is kept in the page URL so reload and browser navigation restore it.
Date-time controls display the modeled site's timezone. Saved instants remain unambiguous.

The top bar holds only the site. Each tab that needs an equip (Overview, Charts, Points, FDD, RCx, Export) has its own
equip picker at its top, with weather listed as its own **Weather** entry: weather points are never shown as an equip's
own sensors. On the Charts tab the hour-of-day heat map has a sensor dropdown (the equip's numeric sensors, labelled
with name and unit), and **All signals** plots every numeric signal of the selected equip (the first equip when none is selected) with one y-axis per unit and the
on/off points in a lane underneath.

History loads in bounded chunks and displays a loading state and a visible error if a request fails. The UI merges the
chunks before drawing. Long ranges therefore do not require one oversized API request. NF still resamples history to
the requested interval. Use [Export](export.html) for a CSV.

## Faults lane

Faults appear as a linked 0/1 lane at the bottom of a chart. The signal and fault lanes share zoom and tooltip time.
Zero means assessed and healthy. A missing time is unknown, not healthy. A sensor series appears only for roles the
rule assesses. Old excluded result points are not deleted.

RCx views declare required and optional roles. The tab draws views whose required roles bind to equipment and lists
the rest with missing inputs. See [Modeling](modeling.html) and [FDD rules](fdd-rules.html).

For contributors, register chart views with rcxView in nf-app/static and add them to nf-app/rcx-parity.json. The
fault lane helper is rcxWithFaultLane in nf-app/static/rcx.js. The chart range helpers (the default range is the last 7 days: `DEFAULT_RANGE_PRESET`) live in
shared/static/charts.js (copied to both editions) and are tested in nf-app/tests.
