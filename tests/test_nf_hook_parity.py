"""The pandas NF client matches the hook on the four live gaps: single-AHU run proof, the 50 h/week
occupancy default, the unit spellings ``L/sec`` and ``in h₂0``, and the console env file."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pd = pytest.importorskip("pandas")

from open_fdd.analytics.occupancy import OccupancySchedule, default_hook_schedule, occupied_hours_per_week, occupied_mask
from open_fdd.nf.client import NFClient, NFError
from open_fdd.nf.model import Model, Point, equipment_frames
from open_fdd.nf.rules import run_rules
from open_fdd.nf.units import to_si
from open_fdd.run_proof import derive_run_proof, feeder_proof_points


def _equip(eid: str, markers: str, **attrs):
    return {"name": eid, "pointType": "EQUIPMENT", "attrs": {"id": eid, "siteRef": "s", "markers": markers, **attrs}}


def _point(uuid: str, equip: str, tags: list[str], unit: str = "", kind: str = "Number") -> Point:
    return Point(uuid, uuid, uuid, ["point", *tags], unit, kind, equip, "s", "", "", "", None)


def _model(equips, points) -> Model:
    return Model([], equips, [], points)


class _History:
    def __init__(self):
        self.uuids: list[str] = []

    def point_data(self, uuids, start, end, window_sec=300, **_kw):
        self.uuids = list(uuids)
        t = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
        return {u: [(t, 22.0 if u.startswith("z") else 1.0)] for u in uuids}


def _one_ahu():
    fan = _point("f1", "AHU", ["fan", "run", "sensor"], kind="Bool")
    zone = _point("z1", "V1", ["zone", "air", "temp", "sensor"], unit="°C")
    equips = [_equip("AHU", "equip,ahu"), _equip("V1", "equip,vav")]
    return _model(equips, [fan, zone]), zone, fan


def test_one_ahu_and_no_airref_stamps_run_proof_even_when_only_the_vav_is_requested():
    model, _zone, fan = _one_ahu()
    hist = _History()
    start, end = datetime(2026, 1, 5, tzinfo=timezone.utc), datetime(2026, 1, 6, tzinfo=timezone.utc)
    frames = equipment_frames(hist, model, start, end, equip="V1")
    assert fan.uuid in hist.uuids
    df = frames[("s", "V1")]
    series, src = derive_run_proof(df)
    assert src == "operating_status" and df.attrs["run_proof_source"] == "assumedSingleAhu"
    assert series.notna().all() and float(series.iloc[0]) == pytest.approx(1.0)


def test_single_ahu_assumption_is_off_when_asked_and_does_not_guess_a_dangling_ref_or_two_ahus():
    model, _, fan = _one_ahu()
    hist = _History()
    start, end = datetime(2026, 1, 5, tzinfo=timezone.utc), datetime(2026, 1, 6, tzinfo=timezone.utc)
    frames = equipment_frames(hist, model, start, end, equip="V1", assume_single_feeder=False)
    assert fan.uuid not in hist.uuids and "operating_status" not in frames[("s", "V1")].columns
    dangling = _model(
        [_equip("AHU", "equip,ahu"), _equip("V1", "equip,vav", airRef="missing")],
        [_point("f1", "AHU", ["fan", "run", "sensor"], kind="Bool"),
         _point("z1", "V1", ["zone", "air", "temp", "sensor"], unit="°C")])
    assert feeder_proof_points(dangling) == {}
    two = _model(
        [_equip("A1", "equip,ahu"), _equip("A2", "equip,ahu"), _equip("V1", "equip,vav")],
        [_point("f1", "A1", ["fan", "run", "sensor"], kind="Bool"),
         _point("f2", "A2", ["fan", "run", "sensor"], kind="Bool"),
         _point("z1", "V1", ["zone", "air", "temp", "sensor"], unit="°C")])
    assert feeder_proof_points(two) == {}


def test_vav1_uses_the_50h_default_and_vav2_still_requires_a_point():
    """Monday 07:30 America/Chicago is occupied; 06:30 is not (the Overview default would count 06:30)."""
    early = pd.DatetimeIndex([datetime(2026, 1, 5, 12, 30, tzinfo=timezone.utc)])  # 06:30 Chicago
    later = pd.DatetimeIndex([datetime(2026, 1, 5, 13, 30, tzinfo=timezone.utc)])  # 07:30 Chicago
    sched = OccupancySchedule.from_dict(default_hook_schedule())
    assert occupied_hours_per_week(sched) == pytest.approx(50.0)
    assert bool(occupied_mask(early, sched).iloc[0]) is False
    assert bool(occupied_mask(later, sched).iloc[0]) is True
    assert bool(occupied_mask(early, OccupancySchedule()).iloc[0]) is True

    idx = pd.date_range("2026-01-05 13:30", periods=24, freq="5min", tz="UTC")
    df = pd.DataFrame({"zone-air-temp": 22.0}, index=idx)
    df.attrs.update(equipment_type="VAV", equipment_id="V1", window_sec=300)
    table = run_rules({("s", "V1"): df}, rules=["VAV-1", "VAV-2"])
    v1 = table[table["rule"] == "VAV-1"].iloc[0]
    v2 = table[table["rule"] == "VAV-2"].iloc[0]
    assert v1["raw_status"] == "PASS"
    assert v2["raw_status"] == "SKIPPED_MISSING_ROLES" and "occupancy_status" in v2["missing_roles"]


def test_l_per_sec_and_inches_of_water_digit_zero_convert_to_si():
    flow = to_si(3, "L/sec")
    assert flow is not None and flow.unit == "L/s" and flow.quantity == "flow" and flow.value == pytest.approx(3)
    # subscript 2, digit zero: the NF spelling that is not the letter O in inH₂O
    pressure = to_si(1, "in h₂0")
    assert pressure is not None and pressure.unit == "Pa" and pressure.value == pytest.approx(249.0889)
    assert to_si(1, "in h20").value == pytest.approx(249.0889)


def test_console_env_file_is_the_sync_file(tmp_path):
    envf = tmp_path / "nf_console.env"
    envf.write_text("NF_CONSOLE_URL=https://console.example/\nCONSOLE_USERNAME=ops\nCONSOLE_PASSWORD=secret\n",
                    encoding="utf-8")
    client = NFClient.from_env(env_file=envf, env={})
    assert client.base_url == "https://console.example" and client.auth == ("basic", "ops", "secret")
    with pytest.raises(NFError, match="https"):
        NFClient("http://console.example", pin=True)
