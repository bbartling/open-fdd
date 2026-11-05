# Static Model parser probe

`static_model_probe.py` checks Turtle equivalence with RDFLib, then exercises the
central static UI `loadModelProjection` and `loadModelFromTtl` exports from
`ttl-model.js` (Node). When `openfdd-central` is on `PATH` (or
`OPENFDD_CENTRAL_BIN` is set), the probe also compares counts from live
`GET /api/model/projection` against the JS client and RDF oracle.

```bash
python3 scripts/qualification/semantic/static_model_probe.py \
  --json-out /tmp/static-model-probe.json
python3 -B -m unittest \
  tests.qualification.test_static_model_probe -v
```

Exit 0 means all nonempty cases passed; exit 1 means candidate mismatch; exit 2
means setup/input/output failure. `--cases` accepts a JSON array of unique named
objects with nonempty `ttl` text; each case has the same exact one-equipment,
one-point expectation. `--skip-central` forces the Node + RDFLib path only.

Unit tests inject parser stubs to verify pass and failure semantics without
requiring Node or a central binary on every CI runner.
