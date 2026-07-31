# Phase 3 Outlook — Edge and Live Streaming

## Purpose

Plan the later extension from batch CSV jobs to continuously arriving building
telemetry. This document is architectural foresight only. Phases 1 and 2 must
not broaden BACnet writes, change fieldbus socket ownership, or redesign MQTT
topics merely to make React parity easier.

## Existing constraints to preserve

- `services/fieldbus` owns BACnet/IP and the single UDP 47808 socket.
- Central never touches the BACnet wire.
- The fieldbus container polls and publishes readings to central over MQTTS.
- BACnet client sockets remain ephemeral and do not collide with the hosted
  diagnostic server.
- REST cannot write commandable hosted points.
- Live BACnet writes require explicit human approval and should use dry-run
  first.
- MQTT transport is authenticated/encrypted and site identity is explicit.

React is a control and observation client. It never opens BACnet or MQTT
connections directly to field devices.

## Target data flow

```text
BACnet / Modbus / Haystack / other source
  -> fieldbus Rust drivers
      -> normalized point observation
      -> local buffering and quality metadata
      -> MQTTS publish
  -> central Rust ingest
      -> authentication / authorization / tenant-site routing
      -> deduplication / ordering / clock policy
      -> Arrow historian partitions
      -> job/site dataset references
      -> DataFusion SQL windows and FDD
      -> findings / events / operation status
  -> browser delivery API (SSE or WebSocket where justified)
  -> React live status, trends, faults, and job workflows
```

CSV and live streams should converge on the same normalized observation and
dataset contracts. They are different sources, not different analytics
products.

## Phase 3 prerequisites produced by Phases 1 and 2

- versioned observation, job, run, finding, and chart-dataset contracts;
- React that treats server state as server state;
- asynchronous operation/event model;
- Rust-only package ingest and DataFusion pipeline;
- centralized auth and capability discovery;
- explicit provenance, source, units, quality, and timestamp semantics;
- stable site/equipment/point identities;
- operational metrics and immutable releases.

## Proposed milestones

### P3-M0 — Live observation contract

Define:

- `site_id`, `device_id`, `equipment_id`, `point_id`;
- protocol/source identity;
- event time and ingest time;
- sequence or deduplication identity;
- value and typed representation;
- engineering unit;
- quality/status flags;
- mapping revision;
- source clock quality;
- retained/replayed indicator;
- schema version and producer version.

Decide behavior for:

- out-of-order samples;
- duplicate messages;
- clock jumps;
- reconnect replay;
- unit changes;
- mapping changes;
- late data and FDD recomputation.

### P3-M1 — MQTTS topic and security contract

Document:

- topic hierarchy and versioning;
- client identity and certificate rotation;
- site/tenant authorization;
- QoS and retained-message policy;
- message size and frequency limits;
- offline queue bounds;
- replay and dead-letter behavior;
- broker/central backpressure;
- revocation and compromised-edge procedure.

Tests include invalid certificates, unauthorized topics, reconnect storms,
duplicate QoS delivery, oversized payloads, and bounded offline buffering.

### P3-M2 — Central live ingest/historian

Add:

- normalized decoder;
- idempotent ingest;
- partitioning and retention;
- health/lag/watermark metrics;
- mapping and unit validation;
- quarantine for invalid observations;
- replay-safe DataFusion inputs;
- job/site dataset linking without copying the historian.

### P3-M3 — Live FDD scheduling

Choose and document:

- window trigger;
- watermark and allowed lateness;
- per-site/equipment scheduling;
- confirmation window semantics;
- rule/version rollout;
- recomputation and finding correlation;
- failure isolation;
- resource quotas.

Batch and live runs must yield the same result for the same normalized window
within documented tolerances.

### P3-M4 — React live experience

Add capability-driven UI:

- edge/site online status;
- last observation and ingest lag;
- device/point inventory;
- mapping health;
- live trend with bounded update rate;
- active/recent faults;
- reconnect/stale banners;
- switch between batch job and live site context;
- pause/freeze view without stopping ingestion;
- event history and provenance.

Use SSE initially for server-to-browser status/telemetry if it satisfies scale
and proxy requirements; use WebSocket only for justified bidirectional needs.
Downsample and rate-limit server-side. Do not push every raw point to every
browser.

### P3-M5 — Commissioning and guarded actions

Read-only discovery/status comes first. Any future write workflow requires:

- explicit product authorization;
- role-based permission;
- dry-run;
- point allowlist and priority semantics;
- human confirmation describing exact device/object/value;
- audit log;
- timeout/relinquish behavior;
- emergency disable;
- integration tests on a simulator before a live network.

An AI agent must never perform a live BACnet write without explicit user
approval, regardless of UI capability.

## Phase 3 test themes

- protocol simulators and deterministic playback;
- batch-versus-live equivalence;
- duplicate/out-of-order/late messages;
- DST and clock drift;
- broker and central outage/recovery;
- edge disk exhaustion and queue caps;
- certificate expiry/rotation;
- tenant/site isolation;
- UI stale/reconnect behavior;
- sustained ingest and fan-out load;
- safe BACnet ownership/socket checks.

## Explicit non-goals for Phases 1 and 2

- direct browser-to-MQTT;
- direct browser-to-BACnet;
- a second historian for React;
- live writes as part of UI parity;
- redesigning fieldbus protocol ownership;
- coupling a job to copied raw historian data;
- making Phase 2 deletion depend on unfinished live streaming.
