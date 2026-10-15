#!/usr/bin/env python3
"""Gate47 artifact evaluator — zero-byte / curl-failure must not PASS.

Soft-OPEN ≠ FQ. Synthetic evaluator existence checks are not memory-stress proof.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def eval_workload(path: Path, http_code: int) -> str:
    if http_code != 0:
        raise SystemExit(
            f"FAIL: analytics/runtime HTTP non-zero ({http_code}); curl failure is not PASS"
        )
    if not path.is_file():
        raise SystemExit("FAIL: runtime.json missing (existence required after successful HTTP)")
    raw = path.read_bytes()
    if len(raw) == 0:
        raise SystemExit("FAIL: runtime.json is zero-byte (existence ≠ PASS)")
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — surface parse errors to gate
        raise SystemExit(f"FAIL: runtime.json is not JSON: {e}") from e
    if not isinstance(body, dict):
        raise SystemExit("FAIL: runtime.json root is not an object")
    if body.get("ok") is False and body.get("error"):
        raise SystemExit(f"FAIL: runtime envelope ok=false error={body.get('error')}")
    has_identity = any(
        k in body for k in ("query_id", "building_id", "engine", "analytics_pack", "pack_version")
    )
    semantic = 0
    for key in ("rows", "series", "data", "equipment", "points"):
        val = body.get(key)
        if isinstance(val, list) and len(val) > 0:
            semantic += 1
        elif isinstance(val, dict) and len(val) > 0:
            semantic += 1
    if not has_identity and semantic == 0:
        raise SystemExit("FAIL: runtime.json missing typed identity and nonempty payload fields")
    if len(raw) < 16:
        raise SystemExit("FAIL: runtime.json suspiciously small after parse")
    return (
        "PASS: Gate47 workload — HTTP ok, nonempty typed runtime artifact "
        f"({len(raw)} bytes, semantic_lists={semantic}, identity={has_identity})"
    )


def eval_pressure(
    run_path: Path,
    status_path: Path,
    pressure_http: int,
    status_http: int,
) -> str:
    run_raw = run_path.read_bytes() if run_path.is_file() else b""
    status_raw = status_path.read_bytes() if status_path.is_file() else b""
    if len(run_raw) == 0:
        raise SystemExit(
            f"FAIL: run_now.json zero-byte (http={pressure_http}); pressure proof missing"
        )
    try:
        run_body = json.loads(run_raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"FAIL: run_now.json not JSON: {e}") from e
    if not isinstance(run_body, dict):
        raise SystemExit("FAIL: run_now.json root is not an object")
    if status_http != 0 or len(status_raw) == 0:
        raise SystemExit(
            f"FAIL: scheduler status after pressure http={status_http} bytes={len(status_raw)} "
            "(cancel/drain proof requires reachable nonempty status)"
        )
    try:
        status_body = json.loads(status_raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"FAIL: scheduler_status.json not JSON: {e}") from e
    if not isinstance(status_body, dict):
        raise SystemExit("FAIL: scheduler_status.json root is not an object")
    return (
        "PASS: Gate47 pressure/cancel-drain — nonempty run-now + reachable status "
        f"(run_http={pressure_http}, status_http={status_http}, "
        f"run_bytes={len(run_raw)}, status_bytes={len(status_raw)})"
    )


def _selftest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Mutation: zero-byte runtime must FAIL even if "file exists".
        zero = root / "runtime.json"
        zero.write_bytes(b"")
        try:
            eval_workload(zero, 0)
            raise SystemExit("SELFTEST FAIL: zero-byte accepted")
        except SystemExit as e:
            if "zero-byte" not in str(e):
                raise
        # Mutation: curl failure must FAIL.
        try:
            eval_workload(zero, 22)
            raise SystemExit("SELFTEST FAIL: curl failure accepted")
        except SystemExit as e:
            if "HTTP non-zero" not in str(e):
                raise
        # Happy path: nonempty typed envelope.
        good = root / "runtime_ok.json"
        good.write_text(
            json.dumps(
                {
                    "query_id": "runtime",
                    "building_id": "ACME",
                    "engine": "timescale-sql",
                    "pack_version": "3.6.14-softopen",
                    "rows": [{"equipment_id": "AHU_1", "runtime_hours": 1.0}],
                }
            ),
            encoding="utf-8",
        )
        msg = eval_workload(good, 0)
        assert msg.startswith("PASS:")
        # Pressure: zero-byte run_now FAIL; nonempty + status PASS.
        run_z = root / "run_now.json"
        run_z.write_bytes(b"")
        status = root / "scheduler_status.json"
        status.write_text(json.dumps({"ok": True, "state": "idle"}), encoding="utf-8")
        try:
            eval_pressure(run_z, status, 0, 0)
            raise SystemExit("SELFTEST FAIL: zero-byte pressure accepted")
        except SystemExit as e:
            if "zero-byte" not in str(e):
                raise
        run_z.write_text(json.dumps({"ok": True, "started": True}), encoding="utf-8")
        msg2 = eval_pressure(run_z, status, 0, 0)
        assert msg2.startswith("PASS:")
    print("PASS: gate47_eval_artifacts selftest (zero-byte + curl-failure rejected)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("workload")
    w.add_argument("--path", required=True)
    w.add_argument("--http", type=int, required=True)
    w.add_argument("--pass-file", default="")
    pr = sub.add_parser("pressure")
    pr.add_argument("--run-now", required=True)
    pr.add_argument("--status", required=True)
    pr.add_argument("--run-http", type=int, required=True)
    pr.add_argument("--status-http", type=int, required=True)
    pr.add_argument("--pass-file", default="")
    sub.add_parser("selftest")
    args = p.parse_args(argv)
    if args.cmd == "selftest":
        _selftest()
        return 0
    if args.cmd == "workload":
        msg = eval_workload(Path(args.path), args.http)
        print(msg)
        if args.pass_file:
            Path(args.pass_file).write_text("workload_ok\n", encoding="utf-8")
        return 0
    if args.cmd == "pressure":
        msg = eval_pressure(
            Path(args.run_now),
            Path(args.status),
            args.run_http,
            args.status_http,
        )
        print(msg)
        if args.pass_file:
            Path(args.pass_file).write_text("pressure_ok\n", encoding="utf-8")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
