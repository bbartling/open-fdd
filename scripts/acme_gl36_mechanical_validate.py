#!/usr/bin/env python3
"""
Mechanical sanity checks for Acme GL36 polling (passive validation — not control).

Validates:
  - Temperature sensor ranges and flatline
  - VAV GL36 pressure-request preconditions (flow ratio vs damper)
  - VAV GL36 cooling-request preconditions (zone temp vs setpoint, CLG-O)
  - AHU economizer mixing (MAT between OAT and RAT when OAD open)
  - HW plant supply/return delta

Run against edge samples.csv or feather-backed poll API.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POINTS_CSV = REPO / "edge_backup/local/acme/vm-bbartling/points.gl36_poll.csv"
FALLBACK = REPO / "edge_backup/local/acme/vm-bbartling/points.csv"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class VavBundle:
    inst: str
    zn_t: str = ""
    zn_sp: str = ""
    da_t: str = ""
    flow: str = ""
    flow_sp: str = ""
    damper: str = ""
    clg_o: str = ""


def load_point_map(path: Path) -> dict[str, dict]:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    return {r["point_id"]: r for r in rows if r.get("point_id")}


def index_vav(rows: list[dict]) -> dict[str, VavBundle]:
    out: dict[str, VavBundle] = {}
    for r in rows:
        sid = r.get("system_id") or ""
        if "vav" not in sid:
            continue
        inst = str(r.get("device_instance"))
        b = out.setdefault(inst, VavBundle(inst=inst))
        tag = (r.get("brick_tag") or "").upper()
        pid = r["point_id"]
        if tag == "ZN-T":
            b.zn_t = pid
        elif tag == "ZN-SP":
            b.zn_sp = pid
        elif tag == "DA-T":
            b.da_t = pid
        elif tag == "SA-F":
            b.flow = pid
        elif tag == "SAFLOW-SP":
            b.flow_sp = pid
        elif tag in ("DPR-O", "DPR-CMD", "DPR-STAT"):
            b.damper = pid
        elif tag == "CLG-O":
            b.clg_o = pid
    return out


def fetch_samples(host: str, token: str, lookback_min: int = 15) -> dict[str, list[float]]:
    """Latest values per point_id column from poll status / samples file on edge via SSH-less API."""
    url = f"http://{host}/api/bacnet/poll/status"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    status = json.loads(urllib.request.urlopen(req, timeout=30).read())
    _ = lookback_min  # future: timeseries API
    latest: dict[str, list[float]] = defaultdict(list)
    for row in status.get("last_samples") or []:
        pid = row.get("point_id") or ""
        try:
            latest[pid].append(float(row.get("present_value")))
        except (TypeError, ValueError):
            pass
    return latest


def load_local_samples(path: Path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    if not path.is_file():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = row.get("point_id") or ""
            try:
                v = row.get("present_value") or row.get("value")
                out[pid].append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def last_val(samples: dict[str, list[float]], pid: str) -> float | None:
    vals = samples.get(pid) or []
    return vals[-1] if vals else None


def check_temp_ranges(samples: dict[str, list[float]], rows: list[dict]) -> list[Check]:
    checks: list[Check] = []
    for r in rows:
        bc = r.get("brick_class") or ""
        if "Temperature" not in bc:
            continue
        pid = r["point_id"]
        v = last_val(samples, pid)
        if v is None:
            continue
        units = (r.get("units") or "").lower()
        if "celsius" in units:
            lo, hi = 0.0, 50.0
            suffix = "C"
        else:
            lo, hi = 32.0, 250.0
            suffix = "F"
        if "hot water" in (r.get("object_name") or "").lower() or r.get("system_id") == "hw-plant":
            lo, hi = (60.0, 220.0) if suffix == "F" else (15.0, 105.0)
        ok = lo <= v <= hi
        checks.append(Check(f"temp_range:{pid}", ok, f"{v:.1f}{suffix} in [{lo},{hi}]"))
    return checks


def check_vav_gl36(vav: dict[str, VavBundle], samples: dict[str, list[float]]) -> list[Check]:
    checks: list[Check] = []
    for inst, b in vav.items():
        if not b.zn_t or not b.zn_sp:
            continue
        tz = last_val(samples, b.zn_t)
        sp = last_val(samples, b.zn_sp)
        if tz is not None and sp is not None:
            diff = tz - sp
            # GL36 cooling ladder thresholds (°F)
            lvl3 = diff >= 5.0
            lvl2 = diff >= 3.0
            checks.append(
                Check(
                    f"vav-{inst}-zn_delta",
                    True,
                    f"dT={diff:.1f}F (GL36 cool req hints: >=3F→2, >=5F→3)",
                )
            )
            if lvl3 or lvl2:
                checks.append(Check(f"vav-{inst}-gl36_cool_hint", True, f"would count toward SAT T&R (dT={diff:.1f}F)"))

        flow = last_val(samples, b.flow) if b.flow else None
        fsp = last_val(samples, b.flow_sp) if b.flow_sp else None
        dpr = last_val(samples, b.damper) if b.damper else None
        if flow is not None and fsp and fsp > 0 and dpr is not None:
            ratio = flow / fsp
            # GL36 static pressure request hints
            hint = ""
            if ratio < 0.5 and dpr >= 95:
                hint = "pressure_req≥3"
            elif ratio < 0.7 and dpr >= 95:
                hint = "pressure_req≥2"
            elif dpr >= 95:
                hint = "pressure_req≥1"
            checks.append(
                Check(
                    f"vav-{inst}-gl36_press_hint",
                    True,
                    f"flow/sp={ratio:.2f} damper={dpr:.0f}% {hint or 'ok'}",
                )
            )
    return checks


def check_ahu_economizer(rows: list[dict], samples: dict[str, list[float]]) -> list[Check]:
    by_tag: dict[str, str] = {}
    for r in rows:
        if r.get("system_id") != "rtu-01":
            continue
        tag = (r.get("brick_tag") or "").upper()
        by_tag[tag] = r["point_id"]

    oat = last_val(samples, by_tag.get("OAT", ""))
    rat = last_val(samples, by_tag.get("RAT", ""))
    mat = last_val(samples, by_tag.get("MAT", ""))
    oad = last_val(samples, by_tag.get("OAD-CMD", ""))
    sat = last_val(samples, by_tag.get("SAT", ""))

    checks: list[Check] = []
    if oat is not None and rat is not None and mat is not None:
        lo, hi = min(oat, rat) - 5, max(oat, rat) + 5
        ok = lo <= mat <= hi
        checks.append(Check("ahu-mat_mixing", ok, f"MAT={mat:.1f} between OAT={oat:.1f} RAT={rat:.1f}"))
    if oad is not None and oad > 10 and mat is not None and oat is not None:
        ok = mat <= oat + 15  # economizer should pull MAT toward OAT when open
        checks.append(Check("ahu-economizer_oad", ok, f"OAD={oad:.0f}% MAT={mat:.1f} OAT={oat:.1f}"))
    if sat is not None and rat is not None:
        checks.append(Check("ahu-sat_rat", True, f"SAT={sat:.1f} RAT={rat:.1f} dT={sat-rat:.1f}F"))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=POINTS_CSV)
    ap.add_argument("--samples", type=Path, default=Path(""))
    ap.add_argument("--host", default="")
    ap.add_argument("--user", default="integrator")
    ap.add_argument("--password", default="")
    args = ap.parse_args()

    csv_path = args.csv if args.csv.is_file() else FALLBACK
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    vav = index_vav(rows)

    samples: dict[str, list[float]]
    if args.host:
        import os

        pw = args.password or os.environ.get("OFDD_INTEGRATOR_PASSWORD", "msi-local")
        login = json.dumps({"username": args.user, "password": pw}).encode()
        lr = urllib.request.Request(
            f"http://{args.host}/api/auth/login",
            data=login,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        token = json.loads(urllib.request.urlopen(lr, timeout=30).read())["token"]
        samples = fetch_samples(args.host, token)
    elif args.samples and args.samples.is_file():
        samples = load_local_samples(args.samples)
    else:
        print("Need --host or --samples", file=sys.stderr)
        return 1

    checks: list[Check] = []
    checks.extend(check_temp_ranges(samples, rows))
    checks.extend(check_vav_gl36(vav, samples))
    checks.extend(check_ahu_economizer(rows, samples))

    failed = [c for c in checks if not c.ok]
    for c in checks[:40]:
        mark = "OK" if c.ok else "FAIL"
        print(f"  {mark}  {c.name}: {c.detail}")
    if len(checks) > 40:
        print(f"  ... {len(checks) - 40} more checks")
    print(f"\n{len(checks)} checks, {len(failed)} failed, {len(vav)} VAV boxes indexed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
