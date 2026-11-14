"""Three-way parity, SI: pandas oracle == SQL pack == SPARQL data client (#1618).

The SPARQL leg (sparql_leg.py) serves a synthetic dataset as a synthetic NF, runs the shipped ``sparql-data`` / ``rdf``
hooks in Node over it, fetches with ``open_fdd.nf.sparql_data`` exactly as against a box (flat StartHook args, every
page, one snapshot), builds the SI frames with the package's shared frame assembly, and runs the oracle's own pandas
rule functions (``reference_from_frames``). Then:

* frames: identical to the oracle's input frames (same index, columns, values, dtypes);
* SPARQL client vs pandas oracle: same status and fault hours on every rule and equipment (float noise only);
* SPARQL client vs SQL pack: the same verdict as the oracle under the same Policy, so the oracle's pinned known
  differences (parity_known_differences.json) are the only divergences, and they stay inside their pinned bands.
The stress lane runs the same leg on larger datasets: ``stress.py --sparql``.
"""
from __future__ import annotations

import shutil

import pytest

pd = pytest.importorskip("pandas")
if shutil.which("node") is None:  # pragma: no cover - CI has Node; the lane fails on skip
    pytest.skip("node is required for the hook runner", allow_module_level=True)

from adapters import ADAPTERS  # noqa: E402
from open_fdd.parity import Policy, compare, generate, reference  # noqa: E402
from open_fdd.parity.pandas_ref import equip_frame, weather_frame  # noqa: E402

import sparql_leg as leg  # noqa: E402

CASES = [(0, 2, 2, "basic"), (0, 2, 1, "edge")]


@pytest.fixture(scope="module", params=CASES, ids=lambda c: f"{c[3]}-{c[1]}x{c[2]}")
def case(request):
    seed, equips, days, profile = request.param
    ds = generate(seed, equips, days, profile)
    ad = ADAPTERS["pglite"]()
    ad.load(ds)
    try:
        sql = ad.run()
    finally:
        ad.close()
    assert not ad.stats["errors"], ad.stats["errors"]
    oracle = reference(ds)
    sparql, info = leg.sparql_reference(ds)
    policy = Policy.default(profile, stress=True, dataset=f"{profile}/{seed}/{equips}/{days}")
    return {"ds": ds, "sql": sql, "oracle": oracle, "sparql": sparql, "info": info, "policy": policy}


def test_client_frames_are_the_oracle_frames(case):
    ds = case["ds"]
    _, frames, wx, calls = leg.client_frames(ds)
    assert calls > 1, "the answer must page (points or time)"
    assert set(frames) == {e["equipment_id"] for e in ds.equipment}
    for e, df in frames.items():
        o = equip_frame(ds, e)
        assert list(df.index) == list(o.index), e
        assert sorted(df.columns) == sorted(o.columns), (e, sorted(set(df.columns) ^ set(o.columns)))
        pd.testing.assert_frame_equal(df[o.columns], o, check_freq=False, check_names=False, check_index_type=False)
    w = weather_frame(ds)
    pd.testing.assert_frame_equal(wx[w.columns], w, check_freq=False, check_names=False)


def test_sparql_client_equals_pandas_oracle(case):
    bad = leg.oracle_mismatches(case["sparql"], case["oracle"])
    assert not bad, bad[:20]


def test_sparql_client_equals_sql_pack_like_the_oracle(case):
    v_or = compare(case["sql"], case["oracle"], case["policy"]).to_dict()
    vs = compare(case["sql"], case["sparql"], case["policy"])
    for k in ("compared", "matched", "known_divergent", "unexpected", "unexpected_rules"):
        assert vs.to_dict()[k] == v_or[k], k
    assert vs.ok, vs.summary(False)
    assert vs.compared >= 40 and not vs.pin_violations, vs.pin_violations


def test_the_leg_uses_the_package_rule_functions():
    import inspect

    src = inspect.getsource(leg)
    assert "reference_from_frames" in src and "open_fdd.nf.sparql_data" in src
    assert "def fault" not in src and "hours_true" not in src  # no fault math in the leg