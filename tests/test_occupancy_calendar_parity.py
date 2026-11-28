"""#1636: one saved weekly occupancy calendar gives the same occupied samples in pandas
(open_fdd.analytics.occupancy.occupied_mask) and in the FDD hook (nf-app/static/occupancy.js calendarSchedule +
schedule.js occupied, which the hook writes as occupancy_status for every engine)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.analytics.occupancy import OccupancySchedule, occupied_mask

ROOT = Path(__file__).resolve().parents[1]
CALENDARS = [
    {"timezone": "America/Chicago", "days": {d: {"occupied": d not in ("sat", "sun"), "start": "06:00", "end": "18:00"}
                                             for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}},
    # a shift that wraps past midnight, a short Saturday, a different zone
    {"timezone": "America/New_York", "days": {"mon": {"occupied": True, "start": "22:00", "end": "06:00"},
                                              "tue": {"occupied": True, "start": "07:30", "end": "16:45"},
                                              "sat": {"occupied": True, "start": "09:00", "end": "13:00"},
                                              "sun": {"occupied": False}}},
]
JS = """
const occ = require(process.argv[1] + '/nf-app/static/occupancy.js');
const sched = require(process.argv[1] + '/nf-app/static/schedule.js');
const { calendar, ts } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const s = occ.calendarSchedule(calendar);
process.stdout.write(JSON.stringify(ts.map((t) => (sched.occupied(s, t, s.tz) ? 1 : 0))));
"""


@pytest.mark.parametrize("calendar", CALENDARS)
def test_hook_and_pandas_agree_on_every_five_minutes_of_two_weeks_including_dst(calendar):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the hook side")
    # two weeks across the US fall-back (2026-11-01) so DST is inside the window
    index = pd.date_range("2026-10-26", "2026-11-09", freq="5min", tz="UTC", inclusive="left")
    # missing days take the defaults on both sides (Mon-Fri 06:00-18:00), so the same document goes to both
    pandas = occupied_mask(index, OccupancySchedule.from_dict(calendar)).astype(int).tolist()
    ts = [int(t.value // 1_000_000) for t in index]
    out = subprocess.run([node, "-e", JS, str(ROOT)], input=json.dumps({"calendar": calendar, "ts": ts}),
                         capture_output=True, text=True, check=True)
    hook = json.loads(out.stdout)
    assert len(hook) == len(pandas)
    diff = [str(index[i]) for i, (a, b) in enumerate(zip(hook, pandas)) if a != b]
    assert not diff, f"{len(diff)} samples differ, first {diff[:5]}"
    assert sum(hook) > 0
