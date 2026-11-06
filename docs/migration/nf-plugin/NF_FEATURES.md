---
title: NF features
parent: Architecture
nav_order: 4
---

# What Open-FDD uses from NF's app platform

This file checks which Normal Framework app/plugin features (NF 3.10, `nf://docs/hooks-guide`, docs.normal.dev) the
Open-FDD app uses, and why. The status is as of the `nf-plugin/slice-1` branch.

| NF feature | Open-FDD use | Status |
|---|---|---|
| **App static files** (`/api/v1/apps/static/<app>/`) | The whole UI: Overview, Charts, FDD, RCx, Points, BACnet, Model & RDF. Strict CSP, ECharts vendored, works offline. | ✅ |
| **Portal access** (Normal Online tunnel + Clerk) | The page asks `/api/v1/platform/info` and, behind the portal, sends the console's `ConsoleJWT` bearer. The same UI works on the LAN and through the portal. | ✅ |
| **Haystack model layer** (`point/query layer=model`, `structuredQuery`) | Every site, equip and point the app uses is discovered by tags and NF classes. Nothing site-specific is in the code. | ✅ |
| **Resampled history** (`point/data …&window=Ns&method=`) | The charts, the RCx views and the FDD hook's `history` relation (5-minute grid) all use it. | ✅ |
| **Live push** (`point/updates/data`, gRPC `ObserveDataUpdates`) | Overview cards and sparklines. | ✅ |
| **Scheduled hooks** (rrule) | `weather` (every 20 min) and `fdd` (hourly at :07). | ✅ |
| **On-request hooks** (`StartHook`) | The "Run FDD now" button on the FDD tab and `nf_app_sync.py run --hook fdd`. | ✅ |
| **Hook config** | `fdd`: `engine`, `windowHours`, `equips`, `dryRun`, `bacnet`. `weather`: `site`. | ✅ |
| **App-written points** (`point/points` + `point/data`, "driver pattern") | One result point per equip and rule: an `automation` record holds the history, and a `model` record carries the Haystack tags `fault/metric, fdd, ruleRef, equipRef, siteRef`. Results are trended, queryable and in the RDF. | ✅ |
| **Global variables** | Weather values (`oa_dry_bulb_web` …). | ✅ |
| **NF BACnet server** (`/api/v1/bacnet/local`) | Opt-in (`config.bacnet.enabled`): one AV per equip holding its count of rules in fault, with the rules listed in its description, so any BAS front end can read Open-FDD faults. | ✅ code, off by default |
| **npm dependencies** (`package.json` + `install_dependencies`) | `@electric-sql/pglite` for the full profile. sql.js is vendored, so small edges need no `npm install`. | ✅ |
| **NF MCP** (`manage_app`, `deploy_hook`, `manage_hooks`) | The documented deploy recipe ([Install](../../install.html)). Large files go through `nf_app_sync.py`. | ✅ |
| **Equipment-mode hooks** (`equipment_type_id`, `group_keys`) | Not used on purpose. Equipment types are per site, and the FDD hook binds every equip by tags in one run, which keeps it site-agnostic. | ⏸ by design |
| **Group variables** | Not used. Result points carry Haystack tags and a model record, which group variables can't. | ⏸ by design |
| **`on_data` hooks** | Not used. The rules are window-based (24 h, 5-minute grid), so hourly is the right cadence. | ⏸ by design |
| **TimescaleDB northbound** | Full profile: run the pack inside TimescaleDB over NF's `data` table. **Blocked:** NF doesn't document the schema, and this NF build has no Timescale settings page. Until then, ≥ 3.5 GiB boxes run the exact Postgres pack in PGlite over NF history. | ⛔ needs NF info |
| **Cloud backup** | NF backs up config only, not app files, so the repo (`nf-app/`) plus `nf_app_sync.py` is the app's backup. The result points' history lives in NF's Redis like any other point. | n/a |
| **Schedules / workflows / conversions** | Not needed by FDD. The pack's occupancy roles can bind to NF schedule points by tags if a site models them. | n/a |
