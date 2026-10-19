# OT edge archive — unqualified snapshot `unqualified-cdaa4f15`

This directory is a source snapshot of the BACnet, Modbus, Haystack wire, and MQTTS
broker pieces that 4.0 no longer launches by default. It is **not** a verified
freeze. There is no git tag `ot-mqtt-fieldbus-last-good-*` in this clone, and no
per-platform OCI digest was resolved for a qualified image. Do not call it 3.6.18.

| Fact | Value |
| --- | --- |
| Qualification | `unqualified-snapshot` |
| Source commit | `cdaa4f15c662b8be242c5b0a9ebaed73fbbbc811` |
| Product version on that commit | `4.0.0` (portal salvage, not an OT release pin) |
| Machine manifest | `MANIFEST.json` |
| File checksums | `CHECKSUMS.sha256` (paths relative to `source/`) |

## What is in `source/`

Tested dependency closure for the fieldbus crate and the MQTT broker image:

- `services/fieldbus` including bins `openfdd-fieldbus`, `openfdd-bacnet-modbus`, `openfdd-haystack`
- Docker targets `bacnet-modbus`, `haystack`, `compatibility` in both
  `Dockerfile.closure` (context: `source/`) and `Dockerfile.monorepo-context` (the
  historical repo-root Dockerfile, preserved unchanged)
- `services/mqtt` (`eclipse-mosquitto:2`, config, ACL example, entrypoint)
- Path crates the fieldbus package builds against: `fdd_core`, `openfdd_contracts`,
  `openfdd_connector_runtime`, `openfdd_mqtt`
- `config/fieldbus` with the lab password hash removed and the gateway password blanked
- `edge/src/drivers` protocol tree copy. This is **not** the whole `edge/` crate.
  Shared semantic, package, RDF, and FDD code stays in the live `edge/` crate.

`cargo metadata --no-deps` on `source/Cargo.toml` resolves that closure. A full
image build and an isolated stack boot were **not** run for this snapshot.

## Semantic boundary

Live `open_fdd_edge_prototype` keeps Haystack HTTP and Modbus clients behind the
`ot-transport` feature. That feature is the crate default so the archived edge
binary still builds. `openfdd-central` depends on the crate with
`default-features = false`, so the product library does not link those clients.
The protocol modules were not deleted from the live tree: the edge binary and the
existing fieldbus split gate still compile them. Deleting them from the default
workspace is a later cut.

## 4.0 product path

```bash
./scripts/openfdd_stack_up.sh portal
```

`portal` is central + React web + Timescale. It does not start MQTT or fieldbus.
Central MQTT ingest stays off unless **both** `OPENFDD_MQTT_ENABLED=1` and
`OPENFDD_OT_ARCHIVE_RESTORE=1` are set. A leftover broker variable alone does not
start the OT worker.

Explicit legacy recipes (`react`, `react-ot`, `standalone`, `central`, `edge`) set
the restore flag. They are not the 4.0 default.

## Restore (manual, isolated)

Do not point these binaries at a 4.0 Timescale volume. Compatibility was not proven.

```bash
export OPENFDD_OT_ARCHIVE_RESTORE=1
export OPENFDD_OT_ARCHIVE_TAG=unqualified-not-a-digest
./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh
```

The script renders `recipes/compose.ot-archive.yml` and stops. It does not boot
containers, pull images, or write a database. `--boot` exits 2: boot, health, and
read→ingest→persist→replay evidence are missing (see `evidence/MISSING.md`).

GHCR prune keeps any tag matching `ot-archive-*` or `ot-mqtt-fieldbus-last-good-*`,
and any digest listed in `scripts/ghcr-archive-protected-digests.txt`, even when
the same package version also has an old `sha-*` or old semver tag. No digest is
listed yet because none was verified.

Archived images are not a security-support commitment.
