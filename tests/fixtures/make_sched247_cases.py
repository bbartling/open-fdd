"""Write tests/fixtures/sched247_cases.json: the SCHED-247 proof/completeness scenarios of #1670.

One equipment per scenario; rows carry epoch-ms ``ts`` and the SQL proof columns (``supply_fan_operating_status``, ``supply_fan_command``).
Expected values are SI hours. Regenerate with ``python tests/fixtures/make_sched247_cases.py``; the cases are
deterministic (no RNG).
"""
from __future__ import annotations

import json
from pathlib import Path

START = 1767225600000  # 2026-01-01T00:00:00Z
MIN = 60_000
OUT = Path(__file__).with_name("sched247_cases.json")


def grid(minutes_total: int, step: int = 5) -> list[int]:
    return [START + m * MIN for m in range(0, minutes_total + 1, step)]


def rows(ts: list[int], status=None, cmd=None) -> list[dict]:
    out = []
    for i, t in enumerate(ts):
        s = status(i, t) if callable(status) else status
        c = cmd(i, t) if callable(cmd) else cmd
        out.append({"ts": t, "supply_fan_operating_status": s, "supply_fan_command": c})
    return out


def irregular(minutes_total: int, gap_at: int, gap_min: int) -> list[int]:
    """2,3,5,7,8-minute cycle with one gap of ``gap_min`` minutes starting at ``gap_at``."""
    steps, ts, m, k = [2, 3, 5, 7, 8], [], 0, 0
    while m <= minutes_total:
        ts.append(START + m * MIN)
        if gap_at <= m < gap_at + steps[k % 5]:
            m += gap_min
        else:
            m += steps[k % 5]
        k += 1
    return ts


DAY = 24 * 60
CASES = [
    # name, rows, expected (None = do not check that field)
    ("on_full_day", rows(grid(DAY), status=1.0),
     {"assessment": "assessed", "window_hours": 24.0, "proven_on_hours": 24.0, "proven_off_hours": 0.0,
      "unknown_hours": 0.0, "fault_hours": 24.0 - 55 / 60, "covered_hours": 24.0}),
    ("off_full_day", rows(grid(DAY), status=0.0),
     {"assessment": "assessed", "proven_on_hours": 0.0, "proven_off_hours": 24.0, "fault_hours": 0.0}),
    ("proof_missing_full_day", rows(grid(DAY)),
     {"assessment": "no_proof", "proven_on_hours": 0.0, "proven_off_hours": 0.0, "unknown_hours": 24.0,
      "fault_hours": None, "covered_hours": 0.0}),
    # the #1670 repro: 48 five-minute samples (3.92 h) of ON cannot prove a day always on
    ("on_sparse_48_samples", rows(grid(47 * 5), status=1.0),
     {"assessment": "insufficient_proof", "proven_on_hours": 47 * 5 / 60, "fault_hours": None}),
    # status beats command per sample: status 1 / command 0 is ON; where status is missing the command decides
    ("status_beats_command", rows(grid(DAY), status=lambda i, t: 1.0 if i % 2 == 0 else None,
                                  cmd=lambda i, t: 0.0 if i % 2 == 0 else 0.8),
     {"assessment": "assessed", "proven_on_hours": 24.0, "proven_off_hours": 0.0}),
    ("command_beats_nothing_off", rows(grid(DAY), status=lambda i, t: 1.0 if i % 2 == 0 else None, cmd=0.0),
     {"assessment": "assessed", "proven_on_hours": 12.0, "proven_off_hours": 12.0, "fault_hours": 0.0}),
    # half the day the proof is missing: unknown is not OFF, and too little is known for a verdict
    ("half_unknown", rows(grid(DAY), status=lambda i, t: 1.0 if i < 144 else None),
     {"assessment": "insufficient_proof", "proven_on_hours": 12.0, "proven_off_hours": 0.0, "unknown_hours": 12.0,
      "fault_hours": None}),
    # irregular cadence with a 90-minute gap (> MAX_GAP_HOURS): the gap is unknown time, 23.5 of 25 h known
    ("irregular_with_gap", rows(irregular(25 * 60, 600, 90), status=1.0),
     {"assessment": "assessed", "window_hours": None}),
    # a 3-hour gap leaves too little known proof (< 90% of the window)
    ("irregular_long_gap", rows(irregular(26 * 60, 600, 180), status=1.0),
     {"assessment": "insufficient_proof", "fault_hours": None}),
    # 23 h ON + 1 h OFF = 0.958 >= 0.95: fault on the confirmed ON time (the first 55 min of a streak confirm it); 22 h ON + 2 h OFF = 0.917 < 0.95: no fault
    ("mostly_on_qualifies", rows(grid(DAY), status=lambda i, t: 0.0 if i < 12 else 1.0),
     {"assessment": "assessed", "proven_on_hours": 23.0, "proven_off_hours": 1.0, "fault_hours": 23.0 - 55 / 60}),
    ("mostly_on_below_threshold", rows(grid(DAY), status=lambda i, t: 0.0 if i < 24 else 1.0),
     {"assessment": "assessed", "proven_on_hours": 22.0, "proven_off_hours": 2.0, "fault_hours": 0.0}),
    # boolean start/stop: on when > 0.5; exactly 0.5 is OFF
    ("command_at_threshold_is_off", rows(grid(DAY), cmd=0.5),
     {"assessment": "assessed", "proven_on_hours": 0.0, "proven_off_hours": 24.0, "fault_hours": 0.0}),
    ("command_above_threshold_is_on", rows(grid(DAY), cmd=0.500001),
     {"assessment": "assessed", "proven_on_hours": 24.0, "fault_hours": 24.0 - 55 / 60}),
]


def main() -> None:
    doc = {
        "_doc": __doc__.strip(),
        "params": {"ALWAYS_ON_PCT": 95.0, "CONFIRM_SECONDS": 3600, "MAX_GAP_HOURS": 1.0},
        "tolerance_hours": 1e-6,
        "cases": [{"equipment_id": name, "rows": r, "expected": exp} for name, r, exp in CASES],
    }
    # compact: one line per case, so the fixture stays reviewable in a diff
    head = json.dumps({k: v for k, v in doc.items() if k != "cases"}, indent=1)
    cases = ",\n".join("  " + json.dumps(c, separators=(",", ":")) for c in doc["cases"])
    OUT.write_text(head[:-2] + ',\n "cases": [\n' + cases + "\n ]\n}\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(CASES)} cases)")


if __name__ == "__main__":
    main()
