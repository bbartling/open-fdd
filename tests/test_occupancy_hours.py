"""Weekly occupancy calendar: bare-minimum occupied hours per week, Python == the dashboard's JS (static/occupancy.js)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from open_fdd.analytics.occupancy import DaySchedule, OccupancySchedule, occupied_hours_per_week

ROOT = Path(__file__).resolve().parents[1]


def _cal(**days):
    s = OccupancySchedule()
    for d, v in days.items():
        s.days[d] = DaySchedule(*v)
    return s


CASES = [
    ("default", OccupancySchedule(), 60.0),
    ("all-unoccupied", _cal(**{d: (False, "06:00", "18:00") for d in ("mon", "tue", "wed", "thu", "fri")}), 0.0),
    ("sunday-night-wraps", _cal(sun=(True, "22:00", "06:00")), 68.0),
    ("end-equals-start-is-24h", _cal(sat=(True, "07:00", "07:00")), 84.0),
    ("half-hours", _cal(mon=(True, "07:15", "16:45")), 57.5),
]


@pytest.mark.parametrize("name,sched,hours", CASES, ids=[c[0] for c in CASES])
def test_occupied_hours_per_week(name, sched, hours):
    assert occupied_hours_per_week(sched) == pytest.approx(hours)


def test_from_dict_round_trip_keeps_hours():
    s = _cal(sun=(True, "22:00", "06:00"))
    back = OccupancySchedule.from_dict(json.loads(json.dumps(s.to_dict())))
    assert back.to_dict() == s.to_dict()
    assert occupied_hours_per_week(back) == 68.0


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_mirror_matches_python():
    docs = [c[1].to_dict() for c in CASES]
    script = (
        "const O=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
        "console.log(JSON.stringify(JSON.parse(s).map(c=>O.occupiedHoursPerWeek(O.normalizeCalendar(c)))))})"
    )
    out = subprocess.run(["node", "-e", script, str(ROOT / "nf-app/static/occupancy.js")], input=json.dumps(docs),
                         capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [pytest.approx(c[2]) for c in CASES]