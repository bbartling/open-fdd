# OT edge archive — unqualified snapshot `unqualified-cdaa4f15`

The later live OT tree (fieldbus, broker, drivers, compose, CI) now lives in
[`../unmaintained/`](../unmaintained/README.md). This directory stays the
checksummed pin of commit `cdaa4f15`. Do not edit `source/` or
`CHECKSUMS.sha256`. Where the trees overlap, `unmaintained/` is the newer copy.

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

`cargo metadata --no-deps` on `source/Cargo.toml` resolves that closure. The
captured `source/Cargo.lock` still lists parent-workspace crates, so
`cargo --locked` on that file fails. The protocol split gate copies this tree
and regenerates the lock in a temp directory before compiling. The checksummed
lock is not rewritten. A container boot was **not** run.

## Semantic boundary

The product `edge/` crate is the CSV/NF role and RDF library. Protocol clients
and the edge process are in `../unmaintained/`. `openfdd-central` does not link
`openfdd_mqtt`. This snapshot's `source/` is frozen and is not the product build.

## 4.0 product path

```bash
./scripts/openfdd_stack_up.sh portal
```

`portal` is central + React web + Timescale. Ingest is the Normal Framework portal
and CSV. Central does not start MQTT or fieldbus.

## Restore (manual, isolated)

Do not point these binaries at a 4.0 Timescale volume. Compatibility was not proven.

```bash
export OPENFDD_OT_ARCHIVE_RESTORE=1
./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```

`--replay` reads `evidence/oci-pin.json`, renders `recipes/compose.ot-archive.yml`
with those index digests, and stops. It does not boot containers, pull images, or
write a database. `--boot` exits 2 (see `evidence/MISSING.md`).

The pin is a GHCR resolve of one published fieldbus/mqtt tag. It is not this
snapshot's source commit and it is not a git freeze tag.

GHCR prune keeps any tag matching `ot-archive-*` or `ot-mqtt-fieldbus-last-good-*`,
and any digest listed in `scripts/ghcr-archive-protected-digests.txt`, even when
the same package version also has an old `sha-*` or old semver tag. The committed
pin digests are in that file.

Archived images are not a security-support commitment.
