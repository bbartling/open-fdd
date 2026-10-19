# Missing qualification evidence

This snapshot is unqualified. The following are still true:

1. There is no git freeze tag. The OCI pin in `evidence/oci-pin.json` is a GHCR resolve of a published fieldbus/mqtt tag, not a freeze of commit `cdaa4f15`.
2. Per-platform linux digests for that published tag are recorded and prune-protected. They were not produced by building this snapshot.
3. An isolated disposable boot (central, web, mqtt, fieldbus, database) was not run. `--boot` exits 2.
4. `--replay` renders the pinned compose file and checks the pin. It does not pull, start containers, or replay samples into a database.
5. Timescale schema compatibility with archived binaries was not proven.
6. Ongoing security support is not claimed. Known defects in the archived tree are whatever the source commit contained.

The 4.0 product workspace does not compile live `services/fieldbus`. The archive workspace remains the isolated compile lane.
