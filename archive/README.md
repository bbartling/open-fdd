# Archive

Code under this tree is **archived and unmaintained**.

- It is not a Cargo workspace member (`archive` is excluded).
- GitHub Actions does not build or test it.
- It is not published to GHCR.

The product path is the Normal Framework portal: `openfdd-central`, `openfdd-web`, and Timescale.

## OT edge

| Tree | What it is |
| --- | --- |
| [`ot-edge/unqualified-cdaa4f15/`](ot-edge/unqualified-cdaa4f15/README.md) | Checksummed snapshot of commit `cdaa4f15`. OCI pin, restore recipe, and evidence. Do not edit `source/` or `CHECKSUMS.sha256`. |
| [`ot-edge/unmaintained/`](ot-edge/unmaintained/README.md) | Later live BACnet, Modbus, Haystack wire, fieldbus, MQTT broker, and edge process, moved off the product tree with `git mv`. This is the archived source to read. |

Where the two trees overlap, `unmaintained/` is the newer copy. The snapshot stays so its checksums and the isolated restore recipe remain verifiable. They are two generations, not two product copies.

## Restore

Do not point archived binaries at a 4.0 Timescale volume.

```bash
export OPENFDD_OT_ARCHIVE_RESTORE=1
./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```

`--replay` renders the pinned fieldbus and MQTT broker compose file and stops. It does not boot containers or write a database. `--boot` exits 2.

Product central does not subscribe to MQTT. `crates/openfdd_mqtt` and the connector runtime are in the unmaintained tree and are not workspace members. Railway should drop the MQTT broker service on the next deploy. The isolated restore command above only prints the pinned archive images. It does not start central.
