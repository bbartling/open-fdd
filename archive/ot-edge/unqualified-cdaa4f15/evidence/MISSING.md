# Missing qualification evidence

This snapshot is unqualified. The following were not produced:

1. A git tag or other immutable freeze ref (`git tag -l 'ot-mqtt-fieldbus-last-good-*'` was empty).
2. Per-platform OCI digests for `openfdd-central`, `openfdd-web`, `openfdd-mqtt`, and `openfdd-fieldbus` at a qualified OT revision.
3. An isolated disposable boot (central, web, mqtt, fieldbus, database) under `/tmp/openfdd-softopen/`.
4. Rendered-compose proof from a pinned old image set (the restore script only renders this snapshot's compose file).
5. Synthetic read → ingest → persist → replay against archived binaries.
6. A statement that the 4.0 Timescale schema accepts archived writers. It must not be assumed.
7. Ongoing security support. Known defects in the archived tree are whatever the source commit contained; they are not re-triaged here.

SoftOPEN defer — isolated restore boot and digest pin stay open.
