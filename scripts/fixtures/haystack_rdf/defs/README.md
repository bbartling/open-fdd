# Pinned Project Haystack defs (C3 / #1123)

| File | Role |
| --- | --- |
| `defs.ttl` | Official normalized Haystack **4.0.0** Turtle from [project-haystack.org/download/defs.ttl](https://project-haystack.org/download/defs.ttl) |
| `defs.pin.json` | Pin id, source URL, SHA-256, library versions |
| `defs_index.json` | Compact symbol → `{lib,iri,owl,…}` index derived from `defs.ttl` for Rust resolution |

**Compile embed:** the same three files are vendored at
`edge/assets/haystack_rdf/defs/` for `include_str!` (Docker COPY `edge/` only).
Keep the fixture tree and edge assets byte-identical when re-pinning.

**Pin id:** `haystack-defs-ttl-4.0.0`

The RDF documentation page's illustrative prefix version `4.0` is **not** the artifact pin. This download uses library base IRIs under `…/def/{lib}/4.0.0#`.

Re-pin procedure:

```bash
curl -fsSL -o scripts/fixtures/haystack_rdf/defs/defs.ttl \
  https://project-haystack.org/download/defs.ttl
# regenerate defs.pin.json + defs_index.json (see audit train / CI helper)
sha256sum scripts/fixtures/haystack_rdf/defs/defs.ttl
```

Do not invent Haystack IRIs. Unknown application tags stay in native metadata and appear in the projection report.
