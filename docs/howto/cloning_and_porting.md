---
title: Cloning and porting
parent: How-to guides
nav_order: 15
---

# Cloning and porting

The **open-fdd** repo should be portable to another lab, another workstation, or another Open-FDD deployment with minimal conceptual changes. Optional lab/bench assets may live under **`afdd_stack/openclaw/`** when that subtree is present in your checkout.

## Core portability idea

Same tools, any building — only the knowledge graph changes.

That means the repo carries the reusable process, while the live Open-FDD model carries the site-specific truth.

## What should transfer cleanly

- automated tests (`python -m pytest` from the monorepo root with dev deps, plus CI in `.github/workflows/ci.yml`)
- the BACnet fake-device approach ([`afdd_stack/scripts/fake_bacnet_devices/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/scripts/fake_bacnet_devices/README.md))
- the overnight review discipline
- the SPARQL validation patterns ([modeling/sparql_cookbook](../modeling/sparql_cookbook))
- the operator framework ([`afdd_stack/config/ai/operator_framework.yaml`](https://github.com/bbartling/open-fdd/blob/main/afdd_stack/config/ai/operator_framework.yaml))
- the continuous context-backup loop
- the idea of proving telemetry-to-fault correctness rather than only checking page loads

## What usually changes per environment

- frontend URL
- API URL
- API auth setup
- site IDs / names
- BACnet gateway hostnames or IPs
- active Open-FDD rules directory (under `afdd_stack/stack/rules/`, mounted into containers)
- Docker/container naming
- LAN / OT network topology
- the actual HVAC system, naming conventions, and semantic model shape
- SPARQL queries or filters needed for that environment

## What to do when deploying to another site

1. Resolve the target frontend/backend/BACnet endpoints from the real launch context.
2. Confirm auth works from the shell or runtime that will actually run the checks.
3. Query the Open-FDD model first:
   - sites
   - equipment
   - BACnet devices
   - representative outdoor / plant / air / zone points
4. Let the model decide what should be checked at that site.
5. Keep repo docs generic; put site-specific truth into the Open-FDD model instead of hard-coding it into Markdown.

## Recommended first-pass deployment flow for a new building

Use this order on a fresh site:

- verify backend auth and reachability
- run SPARQL/model sanity checks
- discover representative operator-relevant points from the model
- run the daytime smoke suite first ([`openclaw/bench/e2e/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/e2e/README.md))
- fix auth/model/BACnet issues found there before trusting the overnight 12-hour run
- only then move into recurring integrity sweeps and overnight review

## Same-bench OpenClaw clone checklist

If OpenClaw is cloned onto another machine for the **same current test bench**, the new clone should read these first:

1. Root [`README.md`](../../README.md)
2. [`openclaw/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/README.md)
3. [OpenClaw context bootstrap](../operations/openclaw_context_bootstrap)
4. [Open-FDD integrity sweep](../operations/openfdd_integrity_sweep)
5. [Site VOLTTRON and the data plane (ZMQ)](../concepts/site_volttron_data_plane) — verify historian → SQL → FDD chain
6. [`openclaw/bench/fake_bacnet_devices/README.md`](https://github.com/bbartling/open-fdd/tree/main/afdd_stack/openclaw/bench/fake_bacnet_devices/README.md)
7. [Monitor the fake fault schedule](fake_fault_schedule_monitoring)

And it should know these durable facts immediately:

- the fake devices intentionally inject faults on a **UTC** schedule
- the 180°F spike is expected only during the shared out-of-bounds window
- the correct way to judge that spike is to compare live BACnet RPC reads against `openclaw/bench/fake_bacnet_devices/fault_schedule.py`
- the integrity sweep should classify graph drift, auth drift, BACnet drift, and product behavior separately
- durable reasoning belongs in this repo, not only in local OpenClaw chat memory

## Portability goal

A clone of this repo should make it easy for another engineer to answer:

- Check whether Open-FDD is healthy.
- Confirm BACnet scraping is working.
- Verify the building model is usable.
- Are faults being computed here?
- Are regressions visible here before they affect a real deployment?

## Engineering principle

Keep environment-specific values configurable and keep the verification logic reusable.

In practice, deployment to another site usually looks like this:

- Open-FDD runs on some other server (often a Linux box on the OT LAN)
- tooling is cloned onto another machine
- the tooling is pointed at the target Open-FDD URL, auth, BACnet gateway, and rule/model context for that environment

The tooling should therefore be robust to:

- different LAN IP schemes
- different Open-FDD hosts
- different HVAC systems and point naming
- different site/equipment modeling shapes
- different SPARQL needs per deployment

The goal is portability with context, not a one-off lab setup.
