---
title: Issue draft - graph drift after overnight fake-device activity
parent: Appendix
nav_order: 20
---

# Issue draft - graph drift after overnight fake-device activity

Repo target: `bbartling/open-fdd`

## Proposed title

Graph triple count and orphan blank nodes grow during post-overnight bench sweeps while BACnet/auth remain healthy

## Summary

On the Open-FDD test bench, authenticated backend checks and BACnet RPC reads remained healthy after the overnight run, but repeated daytime integrity sweeps showed continuing growth in:

- `triple_count`
- `orphan_blank_nodes`

from `GET /data-model/check`.

This looks like graph hygiene drift or repeated residual graph writes rather than an auth failure or BACnet outage.

## Observed evidence

Authenticated `GET /data-model/check` snapshots on 2026-03-24:

- ~06:11 CDT: `triple_count=92339`, `orphan_blank_nodes=23324`
- ~06:31 CDT: `triple_count=93881`, `orphan_blank_nodes=23726`
- ~06:51 CDT: `triple_count=95166`, `orphan_blank_nodes=24061`
- ~07:11 CDT: `triple_count=96194`, `orphan_blank_nodes=24329`
- ~07:31 CDT: `triple_count=97479`, `orphan_blank_nodes=24664`

At the same time:
- backend auth worked
- BACnet RPC reads worked
- model-derived BACnet addressing remained present

## Why this looks product-level

The drift persisted across multiple sweeps even when:
- auth was healthy
- BACnet transport was healthy
- the test bench remained reachable

That makes this look less like launch-context drift and more like backend graph cleanup / write-path behavior.

## Possible hypotheses

- repeated BACnet discovery merges are leaving residual blank nodes
- post-discovery graph sync is appending instead of replacing some address-related structures
- count-oriented SPARQL parity mismatches may be downstream symptoms of the same graph-hygiene problem

## Repro direction

1. Start from a clean graph on the fake-device bench.
2. Import the test site and run BACnet discovery for fake devices `3456789` and `3456790`.
3. Leave the bench running overnight or re-run the same discovery / scrape workflow.
4. Poll `GET /data-model/check` periodically.
5. Observe whether triple count and orphan blank nodes grow steadily without corresponding intentional model expansion.

## Expected behavior

Counts may change during a real import/discovery event, but they should not keep drifting upward indefinitely on a stable fake bench without a clear reason.

## Actual behavior

Counts kept increasing across post-overnight sweeps while the bench otherwise stayed healthy.
