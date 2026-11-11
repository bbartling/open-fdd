"""Open-FDD parity harness: prove pandas == SQL on the same SI data (``pip install open-fdd``; stdlib + pandas).

    from open_fdd.parity import generate, reference, compare, Policy

    ds = generate(seed=0, equips=8, days=7, profile="basic")      # SI samples + Haystack model + role map
    ref = reference(ds)                                           # pandas rule results (needs pandas)
    rows = my_adapter.run_all(ds)                                 # your engine runs the pack SQL on ds
    verdict = compare(rows, ref, Policy.default())                # tolerance, zero-compared, unexpected divergence
    print(verdict.summary()); assert verdict.ok

See ``docs/rules/parity-harness.md``. ``generate`` and ``compare`` are stdlib only; ``reference`` needs pandas.
"""
from open_fdd.parity.adapters import EngineAdapter, conformance_errors, run_adapter
from open_fdd.parity.dataset import (GENERATOR_VERSION, PROFILES, Dataset, chicago_offset_hours, generate,
                                     published_hashes)
from open_fdd.parity.imperial import from_imperial, to_imperial
from open_fdd.parity.policy import Policy, Verdict, compare, known_differences, verdict_from_counts
from open_fdd.parity.pandas_ref import reference

__all__ = ["Dataset", "EngineAdapter", "GENERATOR_VERSION", "PROFILES", "Policy", "Verdict", "chicago_offset_hours",
           "compare", "conformance_errors", "from_imperial", "generate", "known_differences", "published_hashes",
           "reference", "run_adapter", "to_imperial", "verdict_from_counts"]
