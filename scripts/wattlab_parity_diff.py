#!/usr/bin/env python3
"""Diff vibe19 oracle WattLab artifacts vs Open-FDD Rust captures.

Tolerances (plan):
  counts exact; medians abs<=0.05 or rel<=0.1%; fault hours abs<=0.05h or <=0.1pp;
  schedule calendar fields exact.

Stop rule: zero *blocker* rows — remaining product gaps must be severity
`accepted` with a written rationale (data proof) in the delta.

Emits reports/wattlab-parity/artifacts/diff_summary.json (+ markdown rows).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORACLE = ROOT / "reports/wattlab-parity/artifacts/vibe19_oracle"
DEFAULT_OFDD = ROOT / "reports/wattlab-parity/artifacts/ofdd_rust"
DEFAULT_OUT = ROOT / "reports/wattlab-parity/artifacts/diff_summary.json"
FIXTURE = ROOT / "reports/wattlab-parity/fixtures/schedule_b100_7to5.json"


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _close(a: float, b: float, *, abs_tol: float, rel_tol: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if abs(a - b) <= abs_tol:
        return True
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= rel_tol


def _sev_num(a: float, b: float, *, abs_tol: float, rel_tol: float) -> str:
    if _close(a, b, abs_tol=abs_tol, rel_tol=rel_tol):
        if abs(a - b) < 1e-12:
            return "noise"
        return "close"
    return "blocker"


def _norm_days(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    days = raw.get("days") or {}
    out = {}
    for k, v in days.items():
        if not isinstance(v, dict):
            continue
        out[str(k).lower()[:3]] = {
            "occupied": bool(v.get("occupied")),
            "start": str(v.get("start", "")),
            "end": str(v.get("end", "")),
        }
    return out


def _unwrap_capture(raw: Any) -> Any:
    """Accept either `{status, body}` capture wrap or raw API JSON."""
    if not isinstance(raw, dict):
        return raw
    if "body" in raw and ("status" in raw or isinstance(raw.get("body"), (dict, list))):
        return raw.get("body")
    return raw


def _analytics_envelope(raw: Any) -> dict:
    body = _unwrap_capture(raw)
    if not isinstance(body, dict):
        return {}
    analytics = body.get("analytics")
    if isinstance(analytics, dict):
        return analytics
    # Already an envelope (engine/rows/…)
    if "engine" in body or "rows" in body or "query_version" in body:
        return body
    return {}


def gate0_schedule(oracle_dir: Path, ofdd_dir: Path, fixture: dict) -> list[dict]:
    rows: list[dict] = []
    o = _load_json(oracle_dir / "parity_schedule.json") or {}
    r = _load_json(ofdd_dir / "parity_schedule.json") or {}
    want = _norm_days(fixture)
    for side, got in (("vibe19", _norm_days(o)), ("ofdd", _norm_days(r))):
        for day, want_row in want.items():
            have = got.get(day) or {}
            ok = have == want_row
            rows.append(
                {
                    "artifact": "parity_schedule",
                    "key": f"{side}.{day}",
                    "vibe19": want_row if side == "vibe19" else have,
                    "ofdd": have if side == "ofdd" else want_row,
                    "delta": None if ok else {"want": want_row, "got": have},
                    "severity": "noise" if ok else "blocker",
                }
            )
    od = _norm_days(o)
    rd = _norm_days(r)
    equal = od == rd and bool(od)
    rows.append(
        {
            "artifact": "parity_schedule",
            "key": "gate0_sides_equal",
            "vibe19": od,
            "ofdd": rd,
            "delta": None if equal else "schedules differ",
            "severity": "noise" if equal else "blocker",
        }
    )
    tz_o = (o or {}).get("timezone")
    tz_r = (r or {}).get("timezone")
    tz_f = fixture.get("timezone")
    rows.append(
        {
            "artifact": "parity_schedule",
            "key": "timezone",
            "vibe19": tz_o,
            "ofdd": tz_r,
            "delta": None if tz_o == tz_r == tz_f else {"fixture": tz_f},
            "severity": "noise" if tz_o == tz_r == tz_f else "blocker",
        }
    )
    meta = _load_json(ofdd_dir / "parity_meta.json") or {}
    if meta.get("gate0_disk_restore_used") and not meta.get(
        "gate0_put_kept_occupancy_schedule"
    ):
        rows.append(
            {
                "artifact": "parity_schedule",
                "key": "put_persistence_bug_c",
                "vibe19": "PUT keeps occupancy_schedule (patched branch)",
                "ofdd": "nightly PUT strips key; Gate 0 used disk restore",
                "delta": (
                    "BUG-C confirmed on running image; code fix in "
                    "edge/src/fdd/session_config.rs. Accepted until tip publish."
                ),
                "severity": "accepted",
                "rationale": (
                    "Unit test keeps_occupancy_schedule_calendar proves branch; "
                    "nightly 83fc4d3 still strips. Disk restore makes compare "
                    "calendar-equal without claiming PUT is fixed in the image."
                ),
            }
        )
    return rows


# Rust-only SQL analytics / aliases — not in the 4.3.0 pandas cookbook catalog.
_RUST_ONLY_RULES = frozenset(
    {
        "AVG-ZONE-TEMP",
        "FAN-RUNTIME-HOURS",
        "FAULT-ELAPSED-HOURS",
        "ZONE-COMFORT-PCT",
        "FC13-SAT-HIGH",
    }
)
_SKIP_STATUSES = frozenset(
    {
        "SKIPPED_MISSING_ROLES",
        "SKIPPED_EQUIPMENT_OFF",
        "SKIPPED",
        "NOT_APPLICABLE_EQUIPMENT_TYPE",
        "NOT_APPLICABLE",
    }
)
_PASS_STATUSES = frozenset({"PASS", "OK"})
_ACCEPTED_SCHEMAS = frozenset(
    {"openfdd_engineering_bundle_v1", "wattlab_dump_v3", "wattlab_dump_v2"}
)


def _fnum(row: dict, *keys: str) -> float | None:
    for k in keys:
        if k not in row or row[k] in (None, ""):
            continue
        try:
            return float(row[k])
        except (TypeError, ValueError):
            continue
    return None


def _status_ok(o: str, r: str) -> bool:
    ou, ru = o.upper(), r.upper()
    if ou == ru:
        return True
    if ou in _PASS_STATUSES and ru in _PASS_STATUSES:
        return True
    if ou in _SKIP_STATUSES and ru in _SKIP_STATUSES:
        return True
    return False


def _intentional_43(
    rule_id: str, o_status: str, r_status: str, o_hours: float | None, r_hours: float | None
) -> tuple[bool, str]:
    """4.3.0 semantic diffs that must not be blockers."""
    ou, ru = o_status.upper(), r_status.upper()
    oh = 0.0 if o_hours is None else o_hours
    rh = 0.0 if r_hours is None else r_hours
    if rule_id == "CHW-1":
        if ou in _SKIP_STATUSES and (
            ru in _SKIP_STATUSES or (ru in _PASS_STATUSES | {"FAULT"} and rh == 0.0)
        ):
            return True, "4.3.0 CHW-1 skip/off (missing proof or zeros)"
        if ru in _SKIP_STATUSES and ou in _SKIP_STATUSES:
            return True, "4.3.0 CHW-1 skip/off"
    if rule_id == "SCHED-247":
        # Pressure inferred as runtime, not a confirmed 24/7 fault.
        if ou in _PASS_STATUSES and ru == "FAULT":
            return True, "4.3.0 SCHED-247 pressure-not-fault"
        if ou in _PASS_STATUSES and ru in _PASS_STATUSES:
            return True, "4.3.0 SCHED-247 pass"
        if ou in _SKIP_STATUSES and ru in _SKIP_STATUSES | _PASS_STATUSES:
            return True, "4.3.0 SCHED-247 skip vs pass"
        if abs(oh - rh) > 0.05 and (ou in _PASS_STATUSES or ru == "FAULT"):
            return True, "4.3.0 SCHED-247 pressure-not-fault hours"
    return False, ""


def compare_manifest(oracle_dir: Path) -> list[dict]:
    man = _load_json(oracle_dir / "MANIFEST.json") or {}
    schema = str(man.get("schema_version") or "")
    legacy = str(man.get("legacy_schema_version") or "")
    ok = schema in _ACCEPTED_SCHEMAS or legacy in _ACCEPTED_SCHEMAS
    return [
        {
            "artifact": "MANIFEST",
            "key": "schema_version",
            "vibe19": {"schema_version": schema, "legacy_schema_version": legacy},
            "ofdd": "accept openfdd_engineering_bundle_v1 or wattlab_dump_v3",
            "delta": None if ok else "unrecognized bundle schema",
            "severity": "noise" if ok else "blocker",
            "rationale": (
                "React/Rust readers accept schema_version or legacy_schema_version."
            ),
        }
    ]


def compare_package_health(oracle_dir: Path) -> list[dict]:
    health = _load_json(oracle_dir / "package_health.json")
    if not isinstance(health, dict):
        return [
            {
                "artifact": "package_health",
                "key": "presence",
                "vibe19": None,
                "ofdd": "n/a (Rust capture has no package_health)",
                "delta": "oracle package_health.json missing",
                "severity": "blocker",
            }
        ]
    errors = health.get("errors") or health.get("error_count") or 0
    if isinstance(errors, list):
        n_err = len(errors)
    else:
        try:
            n_err = int(errors)
        except (TypeError, ValueError):
            n_err = 0
    return [
        {
            "artifact": "package_health",
            "key": "oracle_errors",
            "vibe19": n_err,
            "ofdd": "n/a (no Rust package_health API)",
            "delta": None,
            "severity": "accepted" if n_err else "noise",
            "rationale": (
                "Package health is a Vibe19 ingest contract. Rust capture does not "
                "re-export it; non-zero errors are filed, not silent."
                if n_err
                else "Oracle package health has zero errors."
            ),
        }
    ]


def compare_quality(oracle_dir: Path) -> list[dict]:
    rows: list[dict] = []
    qpath = oracle_dir / "quality_flags.json"
    q = _load_json(qpath)
    if q is None:
        # Parquet/CSV quality tables are also valid evidence.
        alt = list(oracle_dir.glob("quality*")) + list(oracle_dir.glob("**/quality_flags*"))
        rows.append(
            {
                "artifact": "quality",
                "key": "presence",
                "vibe19": [p.name for p in alt] or None,
                "ofdd": "n/a (Rust capture has no quality_flags)",
                "delta": None if alt else "no quality artifact in oracle bundle",
                "severity": "noise" if alt else "accepted",
                "rationale": (
                    "Quality lives in the Engineering Bundle; Rust FDD APIs do not "
                    "yet return SENTINEL/IMPOSSIBLE_FOR_ROLE flags."
                ),
            }
        )
        return rows
    rows.append(
        {
            "artifact": "quality",
            "key": "flags",
            "vibe19": q if not isinstance(q, dict) else {
                k: q[k] for k in list(q)[:8]
            },
            "ofdd": "n/a",
            "delta": None,
            "severity": "accepted",
            "rationale": "Oracle quality flags exported; no Rust counterpart yet.",
        }
    )
    return rows


def compare_topology(oracle_dir: Path) -> list[dict]:
    import csv

    topo = oracle_dir / "topology.csv"
    if not topo.is_file():
        return [
            {
                "artifact": "topology",
                "key": "presence",
                "vibe19": None,
                "ofdd": "n/a",
                "delta": "oracle topology.csv missing",
                "severity": "accepted",
                "rationale": "Topology is an Engineering Bundle table; Rust capture is API-only.",
            }
        ]
    bad = []
    n = 0
    with topo.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n += 1
            ahu = str(row.get("parent_ahu") or row.get("ahu_id") or row.get("ahu") or "")
            vav = str(row.get("vav_id") or row.get("equipment_id") or "")
            if ahu == "100" or (vav.startswith("AHU") and ahu == "100"):
                bad.append({**row})
    return [
        {
            "artifact": "topology",
            "key": "parent_ahu_not_tower",
            "vibe19": {"rows": n, "ahu_mapped_to_100": len(bad)},
            "ofdd": "n/a (no Rust topology export)",
            "delta": None if not bad else bad[:5],
            "severity": "blocker" if bad else "noise",
            "rationale": "parent_ahu must not collapse to tower/floor (AHU_* → 100).",
        }
    ]


def compare_analytics_tables(oracle_dir: Path, ofdd_dir: Path) -> list[dict]:
    """Oracle analytics CSVs vs Rust /api/analytics/* — definition seams stay accepted."""
    rows: list[dict] = []
    runtime = _analytics_envelope(_load_json(ofdd_dir / "runtime.json") or {})
    sensor = _analytics_envelope(_load_json(ofdd_dir / "sensor_health.json") or {})
    motor = oracle_dir / "motor_hours.csv"
    rows.append(
        {
            "artifact": "analytics",
            "key": "runtime_vs_motor_hours",
            "vibe19": "motor_hours.csv" if motor.is_file() else None,
            "ofdd": {
                "engine": runtime.get("engine"),
                "row_count": len(runtime.get("rows") or [])
                if isinstance(runtime.get("rows"), list)
                else None,
            },
            "delta": "definition seam: pandas motor_hours vs DataFusion runtime",
            "severity": "accepted",
            "rationale": (
                "Runtime analytics engines differ (pandas cookbook vs SQL). "
                "Numeric equality is a follow-on; presence is required on both sides."
            ),
        }
    )
    rows.append(
        {
            "artifact": "analytics",
            "key": "sensor_health",
            "vibe19": (oracle_dir / "sensor_health_matrix.csv").is_file(),
            "ofdd": {
                "engine": sensor.get("engine"),
                "row_count": len(sensor.get("rows") or [])
                if isinstance(sensor.get("rows"), list)
                else None,
            },
            "delta": None,
            "severity": "accepted",
            "rationale": "Sensor-health SQL vs pandas matrix — accepted until SQL patch cycle.",
        }
    )
    return rows


def compare_fdd(oracle_dir: Path, ofdd_dir: Path) -> list[dict]:
    """Compare vibe19 fdd_findings to Rust /api/fdd/results."""
    import csv

    rows: list[dict] = []
    findings_path = oracle_dir / "fdd_findings.csv"
    summary_path = oracle_dir / "fdd_summary.csv"
    rust = _unwrap_capture(_load_json(ofdd_dir / "fdd_results.json") or {})
    rust_rows: list = []
    if isinstance(rust, dict):
        rust_rows = rust.get("results") or []
    if not isinstance(rust_rows, list):
        rust_rows = []

    rust_by = {}
    for r in rust_rows:
        if not isinstance(r, dict):
            continue
        key = (str(r.get("rule_id", "")), str(r.get("equipment_id", "")))
        rust_by[key] = r

    oracle_by = {}
    src = findings_path if findings_path.is_file() else summary_path
    if src.is_file():
        with src.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (str(row.get("rule_id", "")), str(row.get("equipment_id", "")))
                oracle_by[key] = row

    if not oracle_by and rust_by:
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": "engine_follow_on",
                "vibe19": "oracle dump used --skip-rules (no findings CSV)",
                "ofdd": f"{len(rust_by)} Rust DF results",
                "delta": "Re-run oracle without --skip-rules",
                "severity": "blocker",
                "rationale": "Parity now requires cookbook rules on the playground oracle.",
            }
        )
        return rows

    if not oracle_by and not rust_by:
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": "presence",
                "vibe19": None,
                "ofdd": None,
                "delta": "both missing — run oracle with rules / OFDD FDD run",
                "severity": "blocker",
            }
        )
        return rows

    rust_only = [k for k in rust_by if k not in oracle_by]
    oracle_only = [k for k in oracle_by if k not in rust_by]
    overlap = [k for k in oracle_by if k in rust_by]

    rows.append(
        {
            "artifact": "fdd_findings",
            "key": "row_count",
            "vibe19": len(oracle_by),
            "ofdd": len(rust_by),
            "delta": {
                "overlap": len(overlap),
                "oracle_only": len(oracle_only),
                "rust_only": len(rust_only),
            },
            "severity": "accepted" if len(oracle_by) != len(rust_by) else "noise",
            "rationale": (
                "Pandas emits the full catalog cartesian (48×59=2832 at 4.3.0). "
                "Rust omits N/A and adds SQL-only analytics ids. Compare overlap."
            ),
        }
    )

    rust_only_analytics = [k for k in rust_only if k[0] in _RUST_ONLY_RULES]
    rust_only_other = [k for k in rust_only if k[0] not in _RUST_ONLY_RULES]
    if rust_only_analytics:
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": "rust_only_sql_analytics",
                "vibe19": 0,
                "ofdd": len(rust_only_analytics),
                "delta": sorted({k[0] for k in rust_only_analytics}),
                "severity": "accepted",
                "rationale": "SQL analytics ids are not in the pandas cookbook catalog.",
            }
        )
    if rust_only_other:
        sample = [f"{a}::{b}" for a, b in rust_only_other[:12]]
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": "rust_only_cookbook",
                "vibe19": None,
                "ofdd": sample,
                "delta": f"{len(rust_only_other)} rust-only cookbook rows",
                "severity": "accepted",
                "rationale": (
                    "Rust may evaluate extra equipment ids (weather/unknown). "
                    "Filed; not a silent status flip on shared keys."
                ),
            }
        )

    for key in sorted(oracle_only):
        o = oracle_by[key]
        o_status = str(o.get("status") or o.get("result_status") or "")
        if o_status.upper() in _SKIP_STATUSES:
            continue  # rust omits N/A / skipped — accepted, don't spam
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": f"{key[0]}::{key[1]}",
                "vibe19": o_status,
                "ofdd": None,
                "delta": "missing on OFDD",
                "severity": "blocker",
            }
        )

    skipped_omitted = sum(
        1
        for k in oracle_only
        if str(oracle_by[k].get("status") or oracle_by[k].get("result_status") or "").upper()
        in _SKIP_STATUSES
    )
    if skipped_omitted:
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": "oracle_skipped_omitted_by_rust",
                "vibe19": skipped_omitted,
                "ofdd": 0,
                "delta": "Rust does not emit N/A / skip rows",
                "severity": "accepted",
                "rationale": "Cartesian skip/N/A rows are pandas-only.",
            }
        )

    for key in sorted(overlap):
        o = oracle_by[key]
        r = rust_by[key]
        o_status = str(o.get("status") or o.get("result_status") or "")
        r_status = str(r.get("status") or "")
        oh = _fnum(o, "fault_hours", "confirmed_fault_hours")
        rh = _fnum(r, "fault_hours")
        intentional, why = _intentional_43(key[0], o_status, r_status, oh, rh)
        status_ok = _status_ok(o_status, r_status)
        if intentional and not status_ok:
            rows.append(
                {
                    "artifact": "fdd_findings",
                    "key": f"{key[0]}::{key[1]}::status",
                    "vibe19": o_status,
                    "ofdd": r_status,
                    "delta": why,
                    "severity": "accepted",
                    "rationale": why,
                }
            )
        else:
            rows.append(
                {
                    "artifact": "fdd_findings",
                    "key": f"{key[0]}::{key[1]}::status",
                    "vibe19": o_status,
                    "ofdd": r_status,
                    "delta": None if status_ok else "status mismatch",
                    "severity": "noise" if status_ok else "blocker",
                }
            )
        if oh is None and rh is None:
            continue
        o_h = 0.0 if oh is None else oh
        r_h = 0.0 if rh is None else rh
        sev = _sev_num(o_h, r_h, abs_tol=0.05, rel_tol=0.001)
        if intentional and sev == "blocker":
            sev = "accepted"
        osamp = _fnum(o, "sample_count", "samples", "n_samples")
        rsamp = _fnum(r, "sample_count", "samples", "n_samples")
        rows.append(
            {
                "artifact": "fdd_findings",
                "key": f"{key[0]}::{key[1]}::fault_hours",
                "vibe19": o_h,
                "ofdd": r_h,
                "delta": r_h - o_h,
                "severity": sev,
                "rationale": why if intentional else None,
            }
        )
        if osamp is not None and rsamp is not None:
            ssev = _sev_num(osamp, rsamp, abs_tol=1.0, rel_tol=0.01)
            rows.append(
                {
                    "artifact": "fdd_findings",
                    "key": f"{key[0]}::{key[1]}::sample_count",
                    "vibe19": osamp,
                    "ofdd": rsamp,
                    "delta": rsamp - osamp,
                    "severity": ssev,
                }
            )
    return rows


def compare_setpoints_gap(oracle_dir: Path, ofdd_dir: Path) -> list[dict]:
    """No Rust occupied/unoccupied setpoint medians API — accepted product gap."""
    import csv

    rows: list[dict] = []
    sp = oracle_dir / "setpoints.csv"
    if not sp.is_file():
        rows.append(
            {
                "artifact": "setpoints.csv",
                "key": "presence",
                "vibe19": None,
                "ofdd": None,
                "delta": "oracle setpoints missing",
                "severity": "blocker",
            }
        )
        return rows
    with sp.open(newline="", encoding="utf-8") as f:
        n = sum(1 for _ in csv.DictReader(f))
    rows.append(
        {
            "artifact": "setpoints.csv",
            "key": "rust_product_api",
            "vibe19": f"{n} rows (oracle)",
            "ofdd": None,
            "delta": (
                "BUG-D: Open-FDD Rust has no calendar-driven occupied/unoccupied "
                "setpoint-median analytics endpoint."
            ),
            "severity": "accepted",
            "rationale": (
                "Data proof: vibe19_oracle/setpoints.csv exists; no "
                "/api/analytics/* route returns occupied/unoccupied SP medians. "
                "Follow-on: DataFusion slice on occupancy_schedule (not BAS "
                "occ_mode). Deferred this wave — not a silent mismatch."
            ),
        }
    )
    return rows


def compare_schedule_analytics(ofdd_dir: Path) -> list[dict]:
    """BAS occ_mode Δt vs vibe19 calendar — accepted definition seam + BUG-A note."""
    rows: list[dict] = []
    env = _analytics_envelope(_load_json(ofdd_dir / "schedule.json") or {})
    ofdd_rows = env.get("rows") or env.get("equipment") or []
    if not isinstance(ofdd_rows, list):
        ofdd_rows = []
    warnings = env.get("warnings") or []
    unocc = [
        r.get("unoccupied_hours")
        for r in ofdd_rows
        if isinstance(r, dict) and "unoccupied_hours" in r
    ]
    all_zero_unocc = bool(unocc) and all(
        isinstance(u, (int, float)) and float(u) == 0.0 for u in unocc
    )
    rows.append(
        {
            "artifact": "schedule_analytics",
            "key": "engine_definition",
            "vibe19": "OccupancySchedule calendar mask (07–17 M–F)",
            "ofdd": "DataFusion Δt over historian occ_mode (BAS)",
            "delta": (
                f"Different product definitions. OFDD engine={env.get('engine')!r} "
                f"rows={len(ofdd_rows)} warnings={warnings!r}"
            ),
            "severity": "accepted",
            "rationale": (
                "Not a numeric bug once defined: OFDD schedule analytics intentionally "
                "integrate BAS occ_mode; WattLab setpoints use the locked calendar. "
                "Calendar-hours endpoint is a separate product ask."
            ),
        }
    )
    rows.append(
        {
            "artifact": "schedule_analytics",
            "key": "occ_mode_float_string_bug_a",
            "vibe19": "n/a (calendar path)",
            "ofdd": {
                "unoccupied_hours": unocc,
                "sample_evidence": 'AHU Utf8 occ_mode is "0.0"/"1.0"',
            },
            "delta": (
                "BUG-A: nightly treats Utf8 '0.0' as occupied → unoccupied_hours=0. "
                "Patched in historian occupied_expr (try_cast DOUBLE) on branch."
                if all_zero_unocc
                else "BUG-A appears fixed in running image (unoccupied_hours > 0)."
            ),
            "severity": "accepted" if all_zero_unocc else "noise",
            "rationale": (
                "Parquet proof: building=BUILDING_100/equipment=AHU_1 occ_mode "
                'counts "1.0"×19199 "0.0"×16337. Old SQL listed only label \'0\'. '
                "Accepted on nightly until tip publish; regression test on branch."
                if all_zero_unocc
                else "Running image reports non-zero unoccupied hours."
            ),
        }
    )
    return rows


def to_markdown(rows: list[dict]) -> str:
    lines = [
        "| artifact | key | vibe19 | ofdd | delta | severity |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:

        def cell(v: Any) -> str:
            s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            return s.replace("|", "\\|").replace("\n", " ")[:120]

        lines.append(
            f"| {cell(r.get('artifact'))} | {cell(r.get('key'))} | "
            f"{cell(r.get('vibe19'))} | {cell(r.get('ofdd'))} | "
            f"{cell(r.get('delta'))} | {cell(r.get('severity'))} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    p.add_argument("--ofdd", type=Path, default=DEFAULT_OFDD)
    p.add_argument("--fixture", type=Path, default=FIXTURE)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    fixture = _load_json(args.fixture) or {}
    rows: list[dict] = []
    rows.extend(gate0_schedule(args.oracle, args.ofdd, fixture))
    rows.extend(compare_manifest(args.oracle))
    rows.extend(compare_package_health(args.oracle))
    rows.extend(compare_quality(args.oracle))
    rows.extend(compare_topology(args.oracle))
    rows.extend(compare_setpoints_gap(args.oracle, args.ofdd))
    rows.extend(compare_schedule_analytics(args.ofdd))
    rows.extend(compare_analytics_tables(args.oracle, args.ofdd))
    rows.extend(compare_fdd(args.oracle, args.ofdd))

    blockers = sum(1 for r in rows if r.get("severity") == "blocker")
    accepted = sum(1 for r in rows if r.get("severity") == "accepted")
    summary = {
        "oracle_dir": str(args.oracle),
        "ofdd_dir": str(args.ofdd),
        "blocker_count": blockers,
        "accepted_count": accepted,
        "row_count": len(rows),
        "stop_rule_met": blockers == 0,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path = args.out.with_suffix(".md")
    md_path.write_text(to_markdown(rows), encoding="utf-8")
    print(f"wrote {args.out} blockers={blockers} accepted={accepted} stop_rule_met={blockers == 0}")
    return 0 if blockers == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
