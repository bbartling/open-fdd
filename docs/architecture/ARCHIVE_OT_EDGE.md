# OT edge archive (fieldbus / MQTTS)

**Status:** Unqualified source snapshot. Not a verified freeze. Soft-OPEN ≠ FQ.

**Snapshot:** `archive/ot-edge/unqualified-cdaa4f15/`

**Source commit:** `cdaa4f15c662b8be242c5b0a9ebaed73fbbbc811`

**Claimed freeze tag:** none. `ot-mqtt-fieldbus-last-good-3.6.18` was not found as a git tag and is not a pin.

## Policy

4.0 product ingest is HTTPS vendor portals into central, then Timescale. Haystack
**semantics**, RDF, SPARQL, roles, CSV import, and SQL FDD stay in the product.
BACnet, Modbus, the Haystack **wire** client, and the MQTTS broker are archive-only.

Normal 4.0 does **not** keep publishing or launching those services as the default
stack. `./scripts/openfdd_stack_up.sh` defaults to `portal` (central + web +
Timescale). Legacy recipes (`react`, `react-ot`, `standalone`, `central`, `edge`)
are the explicit OT lane and set `OPENFDD_OT_ARCHIVE_RESTORE=1`.

Central starts MQTT ingest only when `OPENFDD_MQTT_ENABLED=1` **and**
`OPENFDD_OT_ARCHIVE_RESTORE=1`. A stale broker variable on its own does not start
the worker.

The default GHCR publish path builds central and web. It does not build or push
`openfdd-fieldbus`. Archived MQTT still publishes only when the workflow is
dispatched with `publish_archived_ot`. Tip completeness for 4.0 is central + web.
`./scripts/check_ghcr_tip_stack.sh --with-ot` is the archive image check.

GHCR prune keeps a whole package version when any tag matches `ot-archive-*` or
`ot-mqtt-fieldbus-last-good-*`, or when the version digest is listed in
`scripts/ghcr-archive-protected-digests.txt`. The listed digests are the GHCR
index and linux platform digests resolved for the published fieldbus and mqtt
tag recorded in `archive/ot-edge/unqualified-cdaa4f15/evidence/oci-pin.json`.
That resolve is not a git freeze and is not the snapshot commit.

## What the snapshot contains

A dependency closure that `cargo metadata --no-deps` resolves: fieldbus (three
Docker targets and both Dockerfiles), MQTT image context, the fieldbus path crates,
safe fieldbus config examples, and a copy of `edge/src/drivers`. It does not contain
the whole `edge/` tree, secrets, certificate kits, or a database volume.

Live semantic code stays in `edge/` behind the `ot-transport` feature. Central
depends on that crate with `default-features = false`.

## Restore lane

`archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay`
renders the digest-pinned compose file and stops. It does not pull images,
start containers, or attach a database. `--boot` exits 2.

The archive workspace (`source/Cargo.toml`) is the compile lane. The protocol
split gate copies that tree and regenerates its lock in a temp directory,
because the captured `Cargo.lock` still lists parent-workspace crates.
Live `services/fieldbus` is excluded from the default Cargo workspace and from
4.0 publish.

## Not claimed

Container boot, health, and read→ingest→persist against a database were not run.
The published image revision is not this snapshot's source commit. Archived
binaries are not assumed to accept a 4.0 Timescale schema. Archival availability
is not security support. See `archive/ot-edge/unqualified-cdaa4f15/evidence/MISSING.md`.

## Links

- [ADR-011: Pluggable DataProvider](adr-011-pluggable-data-provider.md)
- [ADR-010: Timescale hard cutover](adr-010-timescale-hard-cutover.md)
- Restore render: `archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh`
