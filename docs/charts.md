---
title: Charts and export
parent: Lite vs Full
nav_order: 1
---

# Charts and export

Open-FDD has four chart and data surfaces. **Overview** opens on a single modeled equipment item and lists all of its modeled I/O points (including current-only and Boolean/Enum/String points). **Charts** plots selected point histories, **RCx** renders equipment and site diagnostics, and **FDD** plots rule results, sensor history, and inline Tuners.

When no saved selection exists for a site, **Overview** picks a landing equipment item from fresh, model-bound outside-air temperature (local BAS OAT first, then site weather OAT): below 12 °C opens a boiler or heating-water plant, 12–24 °C opens an RTU, and 24 °C or above opens a chiller or chilled-water plant, falling back deterministically if absent. Manual equipment choices save per exact site ID and stay pinned across live weather refreshes.

Every chart surface defaults to the **last 7 days** (1 hour, 24 hours, 1 week, All, or custom bounds kept in the URL and displayed in the site timezone). History loads in bounded chunks; in the **Full** edition, ranges extending before NF's in-memory retention fall back to the scoped Timescale `history` hook for numeric and Boolean points (non-numeric `String`/`Enum` exclusions and bucket intervals are disclosed).

## Faults lane

Faults appear as a linked 0/1 lane at the bottom of a chart. Zero means assessed and healthy; missing intervals are unknown, never healthy. A sensor series appears only for roles the rule assesses, and stale excluded result points stay hidden without deleting NF history.

RCx views declare required and optional roles in `nf-app/rcx-parity.json` (using `rcxView` and `rcxWithFaultLane`). See the [data model](modeling.html) and [rules](rules/).

## Export

The **Export** tab downloads a single UTF-8 CSV (with BOM) for one selected equipment item over the chosen range (default **24 hours**). Each download joins all modeled I/O points and distinct FDD summary, fault-timeline, and per-sensor fault columns by timestamp, keeps `0`/`false`/`String`/`Enum` values intact, escapes spreadsheet-formula prefixes, and enforces a 200,000-cell / 20 MiB cap with no silent partial downloads.

By default Export reads raw NF `/api/v1/point/data` timestamps (subdividing any batch that hits NF's 10,000-sample cap), falls back to aligned buckets with empty gaps preserved when raw density exceeds the cell cap, and fills older uncovered spans from the Full Timescale `history` hook. For automation use the API in [API reference](fdd-data-access.html).
