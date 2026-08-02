# Phase 5 — Operational twin, replay, and edge streaming

## Objective

Drive the same React/Unity twin contract from offline replay and quality-aware
live BACnet-to-MQTTS observations. This phase is read/observe first; it does not
authorize autonomous control.

## Entry gates

- Stable site/building/equipment/point identity exists.
- Phase 4 viewer is qualified using simulated/replay data.
- Security and operational ownership for edge deployments is approved.
- Time, quality, sequence, and reconnect semantics are specified.

## P5-M0 — Canonical observation and mapping contract

- Normalize CSV, Arrow historian, and MQTT observations to
  `openfdd.observation.v1`.
- Define event vs ingest time, timezone/DST, units, quality, stale/missing,
  duplicate/out-of-order sequences, reconnect, and clock-skew behavior.
- Version point-to-role and point-to-twin bindings.
- Keep raw observation immutable; corrections produce new revisions/provenance.

## P5-M1 — Replay as the first operational mode

- Create bounded replay sessions from approved datasets.
- Controls: start, pause, speed, seek, loop, and deterministic time cursor.
- Replay uses the same subscription APIs as live mode and is labeled `REPLAY`.
- React and Unity remain synchronized through reconnect and seek.
- Add golden timeline tests including DST, gaps, duplicates, and late data.

## P5-M2 — Live MQTTS ingestion and subscriptions

- Mutual TLS identity, topic ACLs, schema/version validation, backpressure,
  deduplication, bounded buffering, and dead-letter/quarantine behavior.
- Central materializes quality-aware observation windows for DataFusion FDD,
  inference, React, and Unity.
- Provide WebSocket or SSE browser subscription with auth, bounded frequency,
  resync tokens, and snapshot-on-reconnect.
- Never connect browsers or Unity directly to the site MQTT broker.

## P5-M3 — Operational inference and FDD overlays

- Define lookback readiness, missing-feature coverage, stale-data policy, model
  cadence, batching, caching, and late-data correction behavior.
- Surface measured vs predicted, residuals, faults, confidence/domain, and data
  quality with explicit provenance.
- Link a spatial fault overlay to exact React evidence and rule parameters.
- A failed model does not interrupt raw telemetry/FDD views.

## P5-M4 — Safe actuation boundary (planning and guarded manual work only)

Default Open-FDD remains read-only. Any future command capability requires a
separate safety case covering allowlisted points, safe ranges/rate limits,
two-person or explicit approval, expiry, preconditions, device feedback,
rollback, site-local interlocks, audit, and emergency disable. Unity scenario
controls are simulations and must never map directly to BACnet writes.

## Phase 5 exit gates

- Replay and live use one versioned observation/binding contract.
- Loss/reorder/reconnect/stale/clock scenarios pass deterministic tests.
- MQTTS identity and ACL tests prevent cross-site data access.
- Browser/Unity remain responsive within defined update and memory budgets.
- All views unmistakably identify live, replay, simulated, and stale states.
- No BAS command is issued by the scenario/viewer path.

