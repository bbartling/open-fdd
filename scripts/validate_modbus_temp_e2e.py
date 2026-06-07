#!/usr/bin/env python3
"""End-to-end validation: fake Modbus temp server → driver → feather → FDD.

Run from repo root (bridge need not be running — uses Python APIs directly):
  python3 scripts/validate_modbus_temp_e2e.py
  python3 scripts/validate_modbus_temp_e2e.py --keep-server

Starts scripts/fake_modbus_temp_server.py, reads via openfdd_bridge modbus stack,
writes feather shards (source=modbus), then runs a flatline FDD rule on the data.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OPENFDD_WORKSPACE_DIR", str(REPO / "workspace"))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5502
DEFAULT_ADDRESS = 100
LABEL = "fake-temp"
SITE_ID = "modbus-e2e"


def _ok(msg: str) -> None:
    print(f"  OK   {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL {msg}", file=sys.stderr)
    raise SystemExit(1)


def _start_server(port: int, *, flatline: float | None = None) -> subprocess.Popen:
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "fake_modbus_temp_server.py"),
        "--host",
        DEFAULT_HOST,
        "--port",
        str(port),
        "--address",
        str(DEFAULT_ADDRESS),
        "--temp",
        "72.0",
        "--drift",
        "0",
    ]
    if flatline is not None:
        cmd.extend(["--flatline", str(flatline)])
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(0.6)
    if proc.poll() is not None:
        out = proc.stdout.read() if proc.stdout else ""
        _fail(f"fake Modbus server exited early:\n{out}")
    return proc


def _server_ready(port: int) -> bool:
    from openfdd_bridge.modbus_service import execute_modbus_read_request

    try:
        result = execute_modbus_read_request(
            {
                "host": DEFAULT_HOST,
                "port": port,
                "unit_id": 1,
                "timeout": 2.0,
                "registers": [
                    {
                        "address": DEFAULT_ADDRESS,
                        "count": 1,
                        "function": "holding",
                        "decode": "uint16",
                        "scale": 0.1,
                        "label": LABEL,
                    }
                ],
            }
        )
        return bool(result.get("readings") and result["readings"][0].get("success"))
    except Exception:
        return False


def _read_and_store(port: int, *, site_id: str) -> dict:
    from openfdd_bridge.modbus_service import execute_modbus_read_request
    from openfdd_bridge.modbus_store import append_samples_and_ingest, upsert_register

    payload = {
        "host": DEFAULT_HOST,
        "port": port,
        "unit_id": 1,
        "timeout": 3.0,
        "registers": [
            {
                "address": DEFAULT_ADDRESS,
                "count": 1,
                "function": "holding",
                "decode": "uint16",
                "scale": 0.1,
                "label": LABEL,
            }
        ],
    }
    result = execute_modbus_read_request(payload)
    reading = (result.get("readings") or [{}])[0]
    if not reading.get("success"):
        _fail(f"Modbus read failed: {reading.get('error')}")
    upsert_register(
        {
            "host": DEFAULT_HOST,
            "port": port,
            "unit_id": 1,
            "address": DEFAULT_ADDRESS,
            "function": "holding",
            "label": LABEL,
            "units": "degF",
            "last_value": str(reading.get("decoded") or ""),
        }
    )
    ingest = append_samples_and_ingest(
        host=DEFAULT_HOST,
        unit_id=1,
        readings=result.get("readings") or [],
        site_id=site_id,
    )
    if not ingest.get("ok"):
        _fail(f"ingest failed: {ingest.get('reason')}")
    return {"reading": reading, "ingest": ingest}


def _feather_has_data(site_id: str, column: str) -> int:
    from openfdd_bridge.data_loader import load_site_frame

    df = load_site_frame(site_id, source="modbus", columns=[column, "timestamp", "site_id"])
    if df is None or df.empty:
        return 0
    if column not in df.columns:
        return 0
    return int(df[column].notna().sum())


def _timeseries_ok(site_id: str, column: str) -> tuple[bool, str]:
    from openfdd_bridge.timeseries_api import read_plot_series

    plot = read_plot_series(site_id, [column], source="modbus", hours=24, limit=200)
    ts = plot.get("timestamps") or []
    col_vals = (plot.get("series") or {}).get(column) or []
    if len(ts) > 0 and any(v is not None for v in col_vals):
        return True, f"{len(ts)} plot points"
    return False, f"timestamps={len(ts)} series={len(col_vals)}"


def _clean_modbus_site(site_id: str) -> None:
    from openfdd_bridge.feather_store import FeatherStore
    from openfdd_bridge.modbus_store import SAMPLES_HEADER
    from openfdd_bridge.paths import modbus_poll_csv

    store = FeatherStore()
    site_dir = store.site_dir("modbus", site_id)
    if site_dir.is_dir():
        for path in site_dir.glob("shard-*"):
            path.unlink(missing_ok=True)
    poll = modbus_poll_csv()
    if not poll.is_file():
        return
    lines = poll.read_text(encoding="utf-8").splitlines()
    header = lines[0] if lines else SAMPLES_HEADER.strip()
    kept = [ln for ln in lines[1:] if f",{site_id}," not in ln]
    poll.write_text(header + ("\n" + "\n".join(kept) if kept else "\n"), encoding="utf-8")


def _run_modbus_fdd(site_id: str, column: str) -> dict:
    from openfdd_bridge.data_loader import load_frame_for_run
    from openfdd_bridge.fdd_runner import _run_one
    from openfdd_bridge.model_service import ModelService

    model = ModelService().load()
    equip_id = "fake-modbus-bench"
    point_id = "mb-fake-temp-demo"

    equipment = list(model.get("equipment") or [])
    if not any(str(e.get("id")) == equip_id for e in equipment if isinstance(e, dict)):
        equipment.append(
            {
                "id": equip_id,
                "site_id": site_id,
                "building_id": "bens-office",
                "label": "Fake Modbus temp bench",
                "brick_type": "Sensor_Equipment",
            }
        )
        model["equipment"] = equipment

    points = list(model.get("points") or [])
    if not any(str(p.get("id")) == point_id for p in points if isinstance(p, dict)):
        points.append(
            {
                "id": point_id,
                "site_id": site_id,
                "building_id": "bens-office",
                "equipment_id": equip_id,
                "external_id": column,
                "brick_type": "Zone_Air_Temperature_Sensor",
                "fdd_input": "zone_temp",
                "description": "Fake Modbus zone temp",
            }
        )
        model["points"] = points

    code = (REPO / "workspace" / "data" / "rules_py" / "flatline_1h.py").read_text(encoding="utf-8")
    rule = {
        "id": "modbus-fake-temp-flatline-e2e",
        "name": "Modbus fake temp flatline e2e",
        "enabled": True,
        "fault_code": "VAV-C",
        "backend": "arrow",
        "code": code,
        "bindings": {"point_ids": [point_id], "equipment_ids": [], "brick_types": []},
        "config": {
            "flatline_tolerance": 0.1,
            "flatline_window_samples": 3,
            "value_column": column,
            "temp_unit": "imperial",
            "rolling_avg_minutes": 1,
        },
    }

    frame, origin = load_frame_for_run(site_id, source="modbus", columns=[column])
    if frame is None or (hasattr(frame, "empty") and frame.empty):
        _fail("no modbus feather frame for FDD")
    return _run_one(
        rule,
        site_id,
        limit=500,
        model=model,
        chunk_hours=0,
        lookback_hours=0,
        frame=frame,
        origin=origin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--site-id", default=SITE_ID)
    parser.add_argument("--keep-server", action="store_true", help="Leave server running after validation")
    parser.add_argument("--no-server", action="store_true", help="Assume server already listening on --port")
    parser.add_argument("--vary-reads", type=int, default=4, help="Reads with drifting temp before flatline")
    parser.add_argument("--flat-reads", type=int, default=8, help="Flatline reads for FDD window")
    args = parser.parse_args(argv)

    print("==> Modbus fake temp E2E validation")
    _clean_modbus_site(args.site_id)
    proc: subprocess.Popen | None = None
    if not args.no_server:
        print(f"==> Start fake Modbus server on {DEFAULT_HOST}:{args.port}")
        proc = _start_server(args.port)
        if not _server_ready(args.port):
            _fail(f"server not reachable on port {args.port}")
        _ok(f"server reachable on {DEFAULT_HOST}:{args.port}")

    try:
        print("==> Varying temperature reads → feather ingest")
        for i in range(max(0, args.vary_reads)):
            _read_and_store(args.port, site_id=args.site_id)
            time.sleep(1.05)

        print("==> Flatline reads (same temperature) for FDD window")
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3)
            proc = None
        if not args.no_server:
            proc = _start_server(args.port, flatline=72.5)
            time.sleep(0.4)
        for _ in range(max(3, args.flat_reads)):
            row = _read_and_store(args.port, site_id=args.site_id)
            decoded = row["reading"].get("decoded")
            print(f"    stored {LABEL}={decoded}")
            time.sleep(1.05)

        n = _feather_has_data(args.site_id, LABEL)
        if n < 3:
            _fail(f"feather modbus/{args.site_id} has only {n} samples for {LABEL}")
        _ok(f"feather store: {n} non-null samples for column {LABEL!r}")

        ts_ok, ts_detail = _timeseries_ok(args.site_id, LABEL)
        if not ts_ok:
            _fail(f"timeseries API returned no modbus rows for fake-temp ({ts_detail})")
        _ok(f"timeseries plot API (source=modbus) — {ts_detail}")

        print("==> FDD flatline rule on modbus feather data")
        run = _run_modbus_fdd(args.site_id, LABEL)
        if run.get("status") != "ok":
            _fail(f"FDD run error: {run.get('error')}")
        flagged = int(run.get("flagged") or 0)
        rows = int(run.get("rows") or 0)
        print(f"    FDD rows={rows} flagged={flagged} backend={run.get('backend')}")
        if flagged < 1:
            _fail("expected flatline FDD to flag at least one row on flat modbus data")
        _ok(f"FDD flagged {flagged} row(s) on flatline modbus temp")

        print("\n==> Modbus E2E validation passed")
        return 0
    finally:
        if proc and proc.poll() is None and not args.keep_server:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
