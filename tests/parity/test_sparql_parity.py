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


def _nanosecond_index(frame):
    """Compare timestamp values independently of pandas 3's inferred resolution (#1730)."""
    return frame.set_axis(frame.index.as_unit('ns'), axis='index')


@pytest.mark.parametrize('unit', ['ms', 'us', 'ns'])
def test_index_resolution_normalization_preserves_exact_values(unit):
    index = pd.date_range('2026-01-01T00:00:00.123', periods=2, freq='5min', tz='UTC')
    expected = pd.DataFrame({'value': [1., 2.]}, index=index.as_unit('ns'))
    actual = expected.set_axis(index.as_unit(unit), axis='index')
    pd.testing.assert_frame_equal(_nanosecond_index(actual), expected)
    shifted = expected.set_axis(expected.index + pd.Timedelta(1, unit='ns'), axis='index')
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(_nanosecond_index(shifted), expected)
    changed = expected.assign(value=[1., 3.])
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(_nanosecond_index(changed), expected)


@pytest.fixture(scope="module", params=CASES, ids=lambda c: f"{c[3]}-{c[1]}x{c[2]}")
def case(request):
    seed, equips, days, profile = request.param
    ds = generate(seed, equips, days, profile)
    ad = ADAPTERS["duckdb"]()
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
        pd.testing.assert_frame_equal(_nanosecond_index(df[o.columns]), _nanosecond_index(o),
                                      check_freq=False, check_names=False)
    w = weather_frame(ds)
    pd.testing.assert_frame_equal(_nanosecond_index(wx[w.columns]), _nanosecond_index(w),
                                  check_freq=False, check_names=False)


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


def test_sweep_population_comes_from_the_fetched_metadata(case):
    """The SV sweep set is what the client derives from the points' own markers, never a fixture overwrite."""
    ds = case["ds"]
    assert case["info"]["sweep_mismatches"] == []
    _, frames, _, _ = leg.client_frames(ds)
    assert leg.sweep_mismatches(ds, frames) == []
    for e, df in frames.items():
        sweep, units = df.attrs["sweep_units"], df.attrs["role_units"]
        assert sweep and set(sweep) < set(units), e          # inputs that are not sensors keep their units, unswept
        assert all(units[c] == u for c, u in sweep.items()), e
    import inspect
    assert 'attrs["role_units"] =' not in inspect.getsource(leg.client_frames)


# ---------------------------------------------------------------------------- Timescale-selected source
def _text_columns(ds):
    from open_fdd.nf.model import column_for
    return {column_for(c["name"]) for c in ds.history_columns if c["type"] == "text"} | \
        {c["name"] for c in ds.history_columns if c["type"] == "text"}


def test_timescale_selected_client_equals_the_oracle_on_numeric_inputs():
    """basic (on the 5-minute grid): source=timescale through the shipped hook and lib/timescale.js historyRoute.

    Timescale stores numbers only, so text points (occupancy mode, ...) have no history there. The comparison is with
    the oracle run on the same frames minus those text columns: every rule, status, hours and gated samples equal.
    """
    from open_fdd.parity.pandas_ref import reference_from_frames

    ds = generate(0, 2, 1, "basic")
    sparql, info = leg.sparql_reference(ds, source="timescale")
    assert info["source"] == "timescale" and info["hook_calls"] > 2 and info["sweep_mismatches"] == []
    text = _text_columns(ds)
    assert text, "the dataset must carry a text point for this test to mean anything"
    frames = {e["equipment_id"]: equip_frame(ds, e["equipment_id"]).drop(columns=[c for c in text], errors="ignore")
              for e in ds.equipment}
    for e, df in frames.items():   # the client marks its sweep set; give the oracle frames the same metadata
        df.attrs["role_units"] = equip_frame(ds, e).attrs.get("role_units", {})
    oracle = reference_from_frames(frames, weather_frame(ds), float(ds.step_seconds))
    bad = leg.oracle_mismatches(sparql, oracle)
    assert not bad, bad[:20]
    full = reference(ds)
    differ = {m.split("/")[0] for m in leg.oracle_mismatches(sparql, full)}
    assert differ and differ <= {"SCHED-1", "VAV-1", "VAV-2"}, differ   # only the text-input rules move


def test_timescale_selected_frames_are_epoch_bucket_means_on_irregular_data():
    """edge (irregular stamps, gaps, duplicates): every numeric column of the client's frame is the mean of the raw
    samples per epoch-aligned 5-minute bucket, labelled by the bucket start; no bucket is split or counted twice."""
    ds = generate(0, 2, 1, "edge")
    _, frames, _, calls = leg.client_frames(ds, source="timescale")
    assert calls > 2
    from open_fdd.nf.model import column_for

    series = leg.nf_world(ds)["series"]       # the raw samples as stored, duplicates included (avg counts each)
    step = f"{ds.step_seconds}s"
    checked = 0
    for e, df in frames.items():
        for c in ds.history_columns:
            col = column_for(c["name"])
            if c["type"] == "text" or col not in df.columns:
                continue
            raw = [(t, v) for t, v in series[leg.point_uuid(e, c["name"])] if not isinstance(v, str)]
            want = pd.Series([float(v) for _, v in raw], index=pd.to_datetime([t for t, _ in raw], unit="ms", utc=True))
            want = want.groupby(want.index.floor(step)).mean()
            got = df[col].dropna()
            assert set(got.index) == set(want.index), (e, col)
            pd.testing.assert_series_equal(got, want.reindex(got.index), check_names=False, check_freq=False,
                                           check_index_type=False, rtol=1e-12, atol=1e-9, obj=f"{e}/{col}")
            checked += 1
    assert checked > 50


def test_the_leg_uses_the_package_rule_functions():
    import inspect

    src = inspect.getsource(leg)
    assert "reference_from_frames" in src and "open_fdd.nf.sparql_data" in src
    assert "def fault" not in src and "hours_true" not in src  # no fault math in the leg


def test_a_unit_with_no_bound_run_proof_is_skipped_by_the_client_too():
    """Every fourth unit has no resolved run proof (NULL). The client frames are stamped resolved like the oracle's,
    so the client skips that unit rather than falling back to its own fan status (the 4x3+ stress tiers hit this)."""
    ds = generate(0, 4, 1, "basic")
    no_proof = ds.equipment[3]["equipment_id"]
    rules = ["FC1", "SV-RANGE"]
    sparql, _ = leg.sparql_reference(ds, rules)
    oracle = reference(ds, rules)
    for r in rules:
        assert sparql[r][no_proof]["status"] == "SKIPPED_NO_RUN_PROOF", (r, sparql[r][no_proof])
    assert not leg.oracle_mismatches(sparql, oracle)

