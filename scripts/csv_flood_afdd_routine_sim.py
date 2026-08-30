#!/usr/bin/env python3
"""Simulate IoT-style CSV flood + updatable AFDD routine on a real building package.

Mimics real-world flow:
  1. Seed site from ``raw_BUILDING_50_openfdd.zip`` (optionally hour-0 only).
  2. Append hourly historian chunks via ``POST /api/csv/import/package/append``.
  3. Run / update an **AFDD routine** (rule set + params) after each append (or every N).

An AFDD routine is a JSON spec: ``rule_ids``, ``params``, optional ``patches`` keyed by
append step to mimic operators tuning thresholds mid-stream.

Example (Liberty B50, 4 hourly steps, run registry after each append)::

  OPENFDD_ADMIN_PASSWORD=… python3 scripts/csv_flood_afdd_routine_sim.py \\
    --package /home/ben/raw_BUILDING_50_openfdd.zip \\
    --building-id BUILDING_50 \\
    --seed-mode truncate-hour0 \\
    --max-hours 4 \\
    --afdd-routine scripts/fixtures/b50_afdd_routine.json \\
    --afdd-every 1

Artifacts: ``reports/eplus-dump/artifacts/csv_flood_sim/<building_id>/sim_log.jsonl``
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eplus_paths import parity_root

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = Path.home() / "raw_BUILDING_50_openfdd.zip"
DEFAULT_ROUTINE = ROOT / "scripts/fixtures/b50_afdd_routine.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 600.0,
) -> dict:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"HTTP {e.code}: {detail[:800]}"}


def login(base: str, user: str, password: str) -> str:
    out = http_json(
        "POST",
        f"{base}/api/auth/login",
        body=json.dumps({"username": user, "password": password}).encode(),
        content_type="application/json",
        timeout=30,
    )
    tok = out.get("access_token") or out.get("token")
    if not tok:
        raise SystemExit(f"login failed: {out}")
    return str(tok)


def detect_ts_col(header: list[str]) -> str:
    for c in ("timestamp_utc", "timestamp", "time", "datetime"):
        if c in header:
            return c
    for c in header:
        if "time" in c.lower():
            return c
    return header[0]


def parse_ts(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hour_bucket(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def load_routine(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def routine_params(routine: dict) -> dict:
    return dict(routine.get("params") or {})


def routine_rule_ids(routine: dict) -> list[str] | None:
    ids = routine.get("rule_ids")
    if ids is None:
        return None
    return [str(x) for x in ids]


def apply_patches(routine: dict, step: int) -> tuple[dict, list[str]]:
    """Return (params, notes) after step-specific patches."""
    params = routine_params(routine)
    notes: list[str] = []
    for patch in routine.get("patches") or []:
        if int(patch.get("append_step", -1)) != step:
            continue
        p = patch.get("params") or {}
        for rid, val in p.items():
            if isinstance(val, dict) and isinstance(params.get(rid), dict):
                merged = dict(params[rid])
                merged.update(val)
                params[rid] = merged
            else:
                params[rid] = val
        notes.append(str(patch.get("note") or f"patch at step {step}"))
    return params, notes


def list_history_entries(zf: zipfile.ZipFile, building_id: str) -> list[tuple[str, str]]:
    """Map each ``…/<equipment_id>/history_wide.csv`` to equipment_id.

    Nested layouts (e.g. ``BUILDING_50/VAV/VAV_100/history_wide.csv``) must use the
    leaf folder (``VAV_100``), not the parent type folder (``VAV``).
    """
    prefix = f"{building_id}/"
    out: list[tuple[str, str]] = []
    for name in zf.namelist():
        if not name.startswith(prefix) or not name.endswith("/history_wide.csv"):
            continue
        parts = name[len(prefix) :].split("/")
        if len(parts) < 2:
            continue
        eq_id = parts[-2]
        if eq_id.lower() in ("weather",):
            continue
        out.append((eq_id, name))
    return sorted(out, key=lambda x: x[0])


def slice_zip_hourly(
    zip_path: Path, building_id: str, max_hours: int | None
) -> tuple[dict[int, dict[str, str]], dict[str, str]]:
    """Return (hour_index -> {equipment_id: csv_text}, seed_hour0 per equipment)."""
    by_hour: dict[int, dict[str, str]] = defaultdict(dict)
    seed_h0: dict[str, str] = {}
    hour_order: list[datetime] = []

    with zipfile.ZipFile(zip_path) as zf:
        for eq_id, entry in list_history_entries(zf, building_id):
            raw = zf.read(entry).decode("utf-8", errors="replace")
            lines = raw.splitlines()
            if len(lines) < 2:
                continue
            reader = csv.reader(lines)
            header = next(reader)
            ts_col = detect_ts_col(header)
            ts_idx = header.index(ts_col)
            rows_by_hour: dict[datetime, list[list[str]]] = defaultdict(list)
            for row in reader:
                if len(row) <= ts_idx:
                    continue
                try:
                    hb = hour_bucket(parse_ts(row[ts_idx]))
                except ValueError:
                    continue
                rows_by_hour[hb].append(row)
                if hb not in hour_order:
                    hour_order.append(hb)
            hour_order.sort()
            if max_hours is not None:
                hour_order = hour_order[:max_hours]
            for i, hb in enumerate(hour_order):
                chunk_rows = rows_by_hour.get(hb) or []
                if not chunk_rows:
                    continue
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(header)
                w.writerows(chunk_rows)
                text = buf.getvalue()
                by_hour[i][eq_id] = text
                if i == 0:
                    seed_h0[eq_id] = text
    return dict(by_hour), seed_h0


def write_seed_zip(
    src_zip: Path, building_id: str, seed_h0: dict[str, str], dest: Path
) -> None:
    """Copy package zip but replace each equipment history_wide.csv with hour-0 slice."""
    with zipfile.ZipFile(src_zip) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith(f"{building_id}/") and item.filename.endswith(
                "/history_wide.csv"
            ):
                parts = item.filename[len(building_id) + 1 :].split("/")
                if len(parts) >= 2:
                    eq_id = parts[-2]
                    if eq_id in seed_h0:
                        data = seed_h0[eq_id].encode("utf-8")
            zout.writestr(item, data)


def import_package(base: str, token: str, zip_path: Path) -> dict:
    body = zip_path.read_bytes()
    return http_json(
        "POST",
        f"{base}/api/csv/import/package",
        token=token,
        body=body,
        content_type="application/zip",
        timeout=1800.0,
    )


def put_session_config(base: str, token: str, cfg: dict, building_id: str) -> dict:
    sess = http_json("GET", f"{base}/api/fdd/session-config", token=token, timeout=30)
    current = (sess.get("config") or {}) if sess.get("ok") else {}
    merged = {**current, **cfg}
    merged.setdefault("schema_version", "openfdd_session_v1")
    merged["params"] = {**(current.get("params") or {}), **(cfg.get("params") or {})}
    return http_json(
        "PUT",
        f"{base}/api/fdd/session-config",
        token=token,
        body=json.dumps({**merged, "building_id": building_id}).encode(),
        content_type="application/json",
        timeout=60.0,
    )


def run_afdd(
    base: str,
    token: str,
    building_id: str,
    rule_ids: list[str] | None,
    params: dict,
) -> dict:
    body: dict[str, Any] = {
        "mode": "registry",
        "building_id": building_id,
        "params": params,
    }
    if rule_ids is not None:
        body["rule_ids"] = rule_ids
    return http_json(
        "POST",
        f"{base}/api/fdd/run",
        token=token,
        body=json.dumps(body).encode(),
        content_type="application/json",
        timeout=1200.0,
    )


def append_hour(
    base: str, token: str, building_id: str, files: dict[str, str]
) -> dict:
    payload = {
        "confirm": True,
        "building_id": building_id,
        "files": [{"equipment_id": eq, "csv": csv} for eq, csv in sorted(files.items())],
    }
    return http_json(
        "POST",
        f"{base}/api/csv/import/package/append",
        token=token,
        body=json.dumps(payload).encode(),
        content_type="application/json",
        timeout=600.0,
    )


def log_line(log_path: Path, record: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    ap.add_argument("--building-id", default="BUILDING_50")
    ap.add_argument(
        "--seed-mode",
        choices=("full", "truncate-hour0"),
        default="truncate-hour0",
        help="full=import entire zip; truncate-hour0=seed first hour only then append rest",
    )
    ap.add_argument("--max-hours", type=int, default=4, help="Hour buckets to simulate (0..N-1)")
    ap.add_argument("--skip-seed", action="store_true", help="Skip package import (site already loaded)")
    ap.add_argument("--afdd-routine", type=Path, default=DEFAULT_ROUTINE)
    ap.add_argument(
        "--afdd-every",
        type=int,
        default=1,
        help="Run AFDD routine every N append steps (0=never)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Slice only; no API calls")
    ap.add_argument("--api-base", default=os.environ.get("OPENFDD_API_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default=os.environ.get("OPENFDD_USER", "admin"))
    ap.add_argument(
        "--password",
        default=os.environ.get("OPENFDD_ADMIN_PASSWORD", "bensbench-local-admin"),
    )
    ap.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Default: reports/eplus-dump/artifacts/csv_flood_sim/<building_id>",
    )
    args = ap.parse_args()

    if not args.package.is_file():
        raise SystemExit(f"package missing: {args.package}")

    art = args.artifact_dir or (
        parity_root() / "artifacts" / "csv_flood_sim" / args.building_id
    )
    log_path = art / "sim_log.jsonl"
    summary_path = art / "sim_summary.json"

    print(f">> slicing {args.package.name} building={args.building_id} max_hours={args.max_hours}")
    by_hour, seed_h0 = slice_zip_hourly(args.package, args.building_id, args.max_hours)
    if not by_hour:
        raise SystemExit("no hourly slices found — check building_id and zip layout")

    routine = load_routine(args.afdd_routine) if args.afdd_routine.is_file() else {}
    print(f">> hours={len(by_hour)} equipment={len(next(iter(by_hour.values())))} routine={args.afdd_routine.name}")

    if args.dry_run:
        summary = {
            "dry_run": True,
            "building_id": args.building_id,
            "hours": len(by_hour),
            "equipment_per_hour": {str(k): len(v) for k, v in by_hour.items()},
            "generated_at": utc_now(),
        }
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return 0

    base = args.api_base.rstrip("/")
    token = login(base, args.user, args.password)
    print(">> logged in")

    if not args.skip_seed:
        if args.seed_mode == "truncate-hour0":
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                seed_zip = Path(tf.name)
            write_seed_zip(args.package, args.building_id, seed_h0, seed_zip)
            print(f">> seed import (hour-0 truncate) {seed_zip}")
            imp = import_package(base, token, seed_zip)
            seed_zip.unlink(missing_ok=True)
        else:
            print(">> seed import (full package)")
            imp = import_package(base, token, args.package)
        log_line(log_path, {"event": "seed", "response": imp, "at": utc_now()})
        if not imp.get("ok"):
            raise SystemExit(f"package import failed: {imp}")
        print(
            f"   ok equipment={imp.get('equipment_written')} rows={imp.get('total_rows')} "
            f"ms={imp.get('total_ms')}"
        )
    else:
        print(">> skip seed")

    # Apply base session_config from package if present in zip
    with zipfile.ZipFile(args.package) as zf:
        sess_name = f"{args.building_id}/session_config.json"
        if sess_name in zf.namelist():
            pkg_sess = json.loads(zf.read(sess_name))
            put = put_session_config(base, token, pkg_sess, args.building_id)
            log_line(log_path, {"event": "session_config_seed", "response": put, "at": utc_now()})

    append_steps = sorted(by_hour.keys())
    if args.seed_mode == "truncate-hour0":
        append_steps = [h for h in append_steps if h > 0]
    elif args.seed_mode == "full":
        append_steps = []

    faults_seen: list[dict] = []
    for step_idx, hour_ix in enumerate(append_steps, start=1):
        files = by_hour[hour_ix]
        print(f">> append step {step_idx}/{len(append_steps)} hour_index={hour_ix} n_equip={len(files)}")
        t0 = time.time()
        resp = append_hour(base, token, args.building_id, files)
        elapsed = time.time() - t0
        log_line(
            log_path,
            {
                "event": "append",
                "step": step_idx,
                "hour_index": hour_ix,
                "elapsed_s": round(elapsed, 2),
                "response": resp,
                "at": utc_now(),
            },
        )
        if not resp.get("ok"):
            print(f"WARN append failed: {resp.get('error')}")
            continue
        merges = resp.get("merges") or []
        added = sum(int(m.get("rows_added") or 0) for m in merges)
        print(f"   rows_added={added} total_ms={resp.get('total_ms')}")

        params, patch_notes = apply_patches(routine, step_idx)
        if patch_notes:
            put = put_session_config(
                base, token, {"params": params}, args.building_id
            )
            log_line(
                log_path,
                {
                    "event": "routine_patch",
                    "step": step_idx,
                    "notes": patch_notes,
                    "response": put,
                    "at": utc_now(),
                },
            )
            print(f"   routine patch: {'; '.join(patch_notes)}")

        if args.afdd_every > 0 and step_idx % args.afdd_every == 0:
            print(f">> AFDD routine step {step_idx}")
            run = run_afdd(
                base,
                token,
                args.building_id,
                routine_rule_ids(routine),
                params,
            )
            log_line(
                log_path,
                {"event": "afdd_run", "step": step_idx, "response": run, "at": utc_now()},
            )
            if run.get("ok"):
                results = run.get("results") or []
                fault_rows = [
                    r
                    for r in results
                    if isinstance(r, dict)
                    and str(r.get("status", "")).upper() == "FAULT"
                ]
                faults_seen.append(
                    {"step": step_idx, "fault_count": len(fault_rows), "sample": fault_rows[:5]}
                )
                print(
                    f"   fdd ok rules_run={run.get('rules_run')} "
                    f"faults={len(fault_rows)} ms={run.get('total_ms')}"
                )
            else:
                print(f"   fdd failed: {run.get('error')}")

    summary = {
        "building_id": args.building_id,
        "package": str(args.package),
        "seed_mode": args.seed_mode,
        "append_steps": len(append_steps),
        "afdd_routine": str(args.afdd_routine),
        "faults_by_step": faults_seen,
        "log": str(log_path),
        "generated_at": utc_now(),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f">> done artifacts → {art}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
