# Static Model parser probe

`static_model_probe.py` compares the current central static UI `parseTtlModel`
output against an independent RDFLib parse of multiple equivalent Turtle
spellings. Every case must parse to a graph isomorphic to the reference and
produce exactly one equipment and one point. The oracle counts come from the
parsed graph contract, never regular expressions over Turtle text. This checks
parser invariance on a synthetic contract; it does not qualify HTTP export,
database bindings, a deployed image, or semantic correctness of arbitrary models.

```bash
python3 scripts/qualification/semantic/static_model_probe.py \
  --json-out /tmp/static-model-probe.json
python3 -B -m unittest \
  tests.qualification.test_static_model_probe -v
```

Exit 0 means all nonempty cases passed; exit 1 means candidate mismatch; exit 2
means setup/input/output failure. `--cases` accepts a JSON array of unique named
objects with nonempty `ttl` text; each case has the same exact one-equipment,
one-point expectation. The current static parser has been observed failing some
equivalent forms (including renamed prefixes/full IRIs). Record each direct
invocation as a candidate-specific result; unit tests use injected parser stubs
so they verify both pass and failure semantics without pinning the product to a
known bug. The probe does not change or provide a replacement for the product
parser.
