---
title: Open-FDD Central / Portfolio / RCx reports
nav_order: 2
parent: Home
---

# Open-FDD Central / Portfolio / RCx reports

Planning doc for the next feature branch: `feature/openfdd-central-portfolio-rcx-reports`.

## Boundary

| Layer | Role |
|-------|------|
| **Open-FDD Edge** | Lives at the building. BACnet, local FDD, model/trends/faults, safe REST APIs. |
| **Open-FDD Central** | Multi-building desk over Tailscale/VPN. No direct BACnet. No equipment commands. Validation jobs, RCx reports, portfolio health. |

Existing code to extend (do not rewrite):

- `portfolio/collector/` — edge login, rollup fetch, CSV history
- `portfolio/dash/` — multi-site Dash dashboard
- `scripts/portfolio_collect.py` — collector CLI
- Edge APIs: `/api/building/portfolio-rollup`, `/api/faults/status`, `/api/fdd/results`

## Incremental build order

1. **Edge registry** — extend `portfolio/sites.json` schema (name, base URL, site_id, last check-in).
2. **Remote edge client** — reuse `portfolio/collector/edge_client.py`; add validation job endpoints.
3. **Portfolio page** — edge health, BACnet/model/fault status, last check-in.
4. **One-off validation** — trigger read-only harness against one edge (`acme_overnight_fdd_validate` pattern).
5. **24-hour validation planner** — dropdown intervals (2h / 6h / 12h), store cycle results.
6. **Fault-hour analytics** — elapsed fault hours from historian + FDD runs.
7. **Minimal DOCX generator** — `python-docx` + `matplotlib` (`BytesIO` charts).
8. **Report download endpoint** — query edges via REST, render `.docx`.
9. **Tests/fixtures** — deterministic edge mocks; no live BACnet in CI.

## RCx report content (normalized roles)

- Elapsed fault hours by equipment/severity
- SAT vs setpoint, duct static vs setpoint
- Fan/motor runtime analytics
- Missing data warnings
- Duplicate/model warnings from edge audit APIs
- **Never** severity-only cards without equipment context

## Prerequisites

- ACME validation PR merged and **3.0.33** deployed (equipment context on live FDD alerts).
- Follow-ups: FDD run-history equipment grouping, RTU role mapping (see [ACME validation follow-ups]({{ "/ops/acme-validation-follow-ups/" | relative_url }})).

## Safety

Central is read-only toward edges. No BACnet writes, commands, or BAS changes from Central.
