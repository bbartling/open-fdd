"""Client SPARQL frames carry the hook's resolved run proof (#1635, client half)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.nf import sparql_data as sd  # noqa: E402
from open_fdd.run_proof import derive_run_proof, proof_on  # noqa: E402

T0 = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
MS0 = int(T0.timestamp() * 1000)
N = 48  # four hours at 5 minutes
DEGC = "\u00b0C"


def _pt(u, role, unit=DEGC, tags=("point", "his", "sensor")):
    return {"dis": u, "unit": unit, "kind": "Number", "cls": "", "tags": list(tags), "equip": "AHU-1", "site": "s1",
            "weather": "", "role": role}


def _answer(*, status=1.0, cmd=100.0, **extra):
    """An AHU whose supply air misses its setpoint by 7 K the whole time, with a fan status and a % fan command."""
    grid = [MS0 + i * 300_000 for i in range(N)]
    ans = {"kind": "select", "vars": ["uuid"], "uuid_var": "uuid", "rows": [], "bucket": "raw",
           "points": {"sat": _pt("sat", "sat"), "satsp": _pt("satsp", "sat_sp"),
                      "fs": _pt("fs", "fan_status", unit="", tags=("point", "his")),
                      "fc": _pt("fc", "fan_cmd", unit="%", tags=("point", "his"))},
           "equips": [{"site": "s1", "id": "AHU-1", "dis": "AHU 1", "tags": ["equip", "ahu"]}],
           "series": {"sat": [[t, 20.0] for t in grid], "satsp": [[t, 13.0] for t in grid],
                      "fs": [[t, status] for t in grid], "fc": [[t, cmd] for t in grid]}}
    ans.update(extra)
    return ans


def _status(ans, rule="AHU-SATDEV"):
    res = sd.run_rules(sd.frames(ans, window_sec=300), [rule])
    row = res[res["rule"] == rule].iloc[0]
    return row["status"], row["notes"]


def test_older_hook_answer_keeps_the_client_fallback():
    fr = sd.frames(_answer(), window_sec=300)
    df = fr[("s1", "AHU-1")]
    assert df.attrs["run_proof_source"] == "client_fallback" and not df.attrs.get("run_proof_resolved")
    series, src = derive_run_proof(df)
    assert src == "fan-status" and series is not None  # the pre-#1635 behaviour, now labeled


def test_no_binding_marker_skips_like_the_hook_and_sql():
    """A unit with a fan-status point but no bound proof: SKIPPED no_run_proof, never assessed from its own status."""
    assert _status(_answer())[0] == "fault"  # without the hook's answer the client assesses it
    ans = _answer(run_proof=[{"site": "s1", "equip": "AHU-1", "uuid": None, "source": "none"}])
    df = sd.frames(ans, window_sec=300)[("s1", "AHU-1")]
    assert df.attrs["run_proof_resolved"] is True and df.attrs["run_proof_source"] is None
    assert "run-proof" not in df.columns and derive_run_proof(df) == (None, "")
    status, notes = _status(ans)
    assert status == "not-assessed" and "no_run_proof" in notes


def test_unlisted_equipment_is_resolved_without_proof():
    ans = _answer(run_proof=[])  # the hook resolved every equipment it returned and listed none with proof
    assert _status(ans)[0] == "not-assessed"


def test_status_off_command_on_uses_the_resolved_status():
    """The hook resolves the proof to the status point: status OFF wins over a command that says ON."""
    ans = _answer(status=0.0, cmd=100.0,
                  run_proof=[{"site": "s1", "equip": "AHU-1", "uuid": "fs", "source": "own_status"}])
    df = sd.frames(ans, window_sec=300)[("s1", "AHU-1")]
    series, src = derive_run_proof(df)
    assert src == "run-proof" and df.attrs["run_proof_source"] == "own_status"
    assert not proof_on(series).any()
    status, _ = _status(ans)
    assert status != "fault"


def test_proof_on_a_separate_point_and_percent_unit():
    """A unit with no status or command of its own, proven by the equipment feeding it (resolved by the hook)."""
    grid = [MS0 + i * 300_000 for i in range(N)]
    bare = _answer()
    for k in ("fs", "fc"):
        bare["points"].pop(k)
        bare["series"].pop(k)
    status, notes = _status(bare)
    assert status == "not-assessed" and "no_run_proof" in notes  # nothing of its own to derive from
    ans = {**bare, "run_proof": [{"site": "s1", "equip": "AHU-1", "uuid": "feeder-fan", "source": "airRef",
                                  "unit": "%"}],
           "run_proof_series": {"feeder-fan": [[t, 80.0] for t in grid]}}
    df = sd.frames(ans, window_sec=300)[("s1", "AHU-1")]
    assert df["run-proof"].round(6).eq(0.8).all() and df.attrs["run_proof_source"] == "airRef"
    assert _status(ans)[0] == "fault"  # the feeder proves it runs, so the rule is assessed


def test_independent_timestamps_join_exactly():
    """Proof samples 60 s off the data grid are not proof on that grid (a missing sample is not proof)."""
    grid = [MS0 + i * 300_000 for i in range(N)]
    half = [[t + 60_000, 1.0] for t in grid[: N // 2]] + [[t, 1.0] for t in grid[N // 2:]]
    ans = _answer(run_proof=[{"site": "s1", "equip": "AHU-1", "uuid": "p", "source": "own_status"}],
                  run_proof_series={"p": half})
    df = sd.frames(ans, window_sec=300)[("s1", "AHU-1")]
    on = proof_on(df["run-proof"])
    assert not on.iloc[: N // 2].any() and on.iloc[N // 2:].all()


def test_pages_merge_run_proof_and_reject_a_change():
    out = sd._empty("raw")
    e = {"site": "s1", "equip": "AHU-1", "uuid": "p", "source": "own_status"}
    sd._merge(out, {"points": {}, "equips": [], "series": {}, "run_proof": [e], "run_proof_series": {"p": [[2, 1.0]]}})
    sd._merge(out, {"points": {}, "equips": [], "series": {}, "run_proof": [e], "run_proof_series": {"p": [[1, 0.0], [2, 1.0]]}})
    sd._dedup(out)
    assert out["run_proof"] == [e] and out["run_proof_series"]["p"] == [[1, 0.0], [2, 1.0]]
    with pytest.raises(sd.PageError, match="changed between pages"):
        sd._merge(out, {"points": {}, "equips": [], "series": {}, "run_proof": [{**e, "uuid": "other"}]})
    with pytest.raises(sd.PageError, match="needs site, equip and uuid"):
        sd._merge(out, {"points": {}, "equips": [], "series": {}, "run_proof": [{"site": "s1"}]})
