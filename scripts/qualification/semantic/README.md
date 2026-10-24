# Parsed RDF semantic qualification

This is independent **Python test tooling**. Product ingestion, storage and APIs
remain Rust/Timescale. The tool makes no network requests and never executes
arbitrary SPARQL, `SERVICE`, update queries, RDF imports or JSON-LD contexts.

Use a dedicated tooling virtual environment, then install
[`requirements.txt`](requirements.txt). RDFLib is deliberately independent of
the product's Oxigraph implementation. The tool parses the repository's official
vendored Haystack 4.0.0 definitions and checks their recorded SHA-256 before use.
It resolves complete, case-sensitive IRIs; prefix presence is not evidence.

```sh
python scripts/qualification/semantic/qualify.py suite \
  --candidate "$(git rev-parse HEAD)" --out /tmp/semantic-controls.json

python -m pytest -q -p no:cacheprovider tests/qualification/test_semantic_qualification.py
```

`suite` must execute the valid fixture and all 12 deliberately broken controls.
Its PASS proves the evaluator rejects those mutations. It **does not qualify a
deployed product**, import/export round trips, live tenant isolation or SQL math.
Each broken model's inner result remains FAIL; the outer control passes because
the named failing assertions were observed. Missing dependencies, dropped
controls, unknown verdicts, failed parsing infrastructure and an empty expected
inventory cannot produce a qualifying result.

For a candidate export, author an independent, nonempty known-answer contract
using [`../fixtures/semantic/expected.json`](../fixtures/semantic/expected.json)
as the schema example. Fetch the authorized site's real strict Turtle export in
the surrounding authenticated harness, then pass the saved snapshot here:

```sh
python scripts/qualification/semantic/qualify.py model \
  --candidate <immutable-commit-or-image-sha> \
  --model /private/artifacts/candidate-export.ttl \
  --expectations /private/artifacts/independent-expectations.json \
  --out /private/artifacts/semantic-result.json
```

The contract names an exact site IRI, exact equipment IRIs, a complete expected
site point inventory and independently chosen candidate point IDs. Fixed SELECT
templates bind those IRIs as RDF terms. Two similar sensors are valid inventory
and must remain AMBIGUOUS until an explicit selected point is supplied. A
`discharge air temp sp` selector chooses a different point from the corresponding
`sensor` selector, regardless of misleading labels. `RTU_01` cannot select
`RTU_010`; a repeated label in another site cannot join the result. This local
scope test is not an HTTP authorization test.

The profile checks defined class/marker IRIs, site/equipment/point references,
one point function, literal kind, explicit numeric unit, historized point
timezone/history mode, exact typed values and dimensional unit compatibility.
The local engineering unit table is intentionally narrow; an unlisted unit is
unready for this qualification profile, not a claim that Haystack forbids it.
The profile/hash and count fields make that boundary reviewable. Unit conversion
and temperature-delta arithmetic remain SQL/oracle qualifications.

`ofdd:seriesKey`, `ofdd:providerInstance` and `ofdd:remotePointId` are explicit
**qualification binding extensions**, not standard Haystack tags or a claim that
today's strict exporter emits all three. Candidate snapshots need the documented
binding projection/adapter to expose those native authoritative bindings. Missing
bindings fail. Do not derive them by splitting names, point IDs or role strings,
and do not fabricate a matching binding to obtain green. Every READY expectation
must independently specify nonempty `series_key`, `provider_instance` and
`remote_point_id`. The verifier compares all three exactly, so a correct local
key pointing to a different provider or remote point fails. A bound key is opaque;
the verifier never interprets its shape. Endpoint URLs,
credentials and executable requests do not belong in the RDF model.

Reports include model, canonical expectations, profile, pinned definitions and
query SHA-256 values, candidate identity, exact selected IDs, executed assertion
and comparison counts, and dependency versions. They omit raw Turtle, arbitrary
literal values and exception text. Exported IDs may still be private, so store
real candidate artifacts under restricted permissions and never publish them
with security evidence. Files are capped at 2 MiB, graphs at 50,000 triples,
selectors at 32, results at 1,000 and the CLI at a 30-second deadline (1–120
seconds configurable). The hard deadline uses POSIX signals; this CLI is for
Linux qualification runners. Imports of `parse_model` must be bounded by the
calling worker's deadline too.

For shared harnesses, `parse_model(str | bytes)` returns a bounded RDFLib graph;
`graph_inventory(graph)` returns parsed exact-type IDs/counts. These helpers
establish syntax/inventory only. The complete known-answer `qualify`/CLI result
is required for semantic/model assertions. A feature honestly reporting
unavailable must remain a delivery gap, even if its honesty check passes.
