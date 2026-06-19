"""Bench device 5007 — enable 1-minute BACnet poll on four model points."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .bacnet_driver_store import driver_tree, merge_commission_rows, set_device_poll
from .commission_client import commission_health, commission_poll_once, commission_poll_status
from .model_service import ModelService
from .paths import repo_root

BENCH_DEVICE_INSTANCE = 5007
DEFAULT_POLL_INTERVAL_S = 60
DEFAULT_DEVICE_ADDRESS = "2000:7"


def _bench_device_address() -> str:
    """MS/TP routed address for bench FEC 5007 (network:station from commission.env / mapping YAML)."""
    yaml_path = repo_root() / "workspace" / "data" / "bench_bacnet_vs_niagara.yaml"
    if yaml_path.is_file():
        try:
            import yaml

            doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            dev = doc.get("bench_device") if isinstance(doc.get("bench_device"), dict) else {}
            addr = str(dev.get("bacnet_device_address") or "").strip()
            if addr:
                return addr
        except Exception:
            pass
    env_path = repo_root() / "workspace" / "bacnet" / "commissioning" / "commission.env"
    mstp_net = "2000"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("MSTP_NET="):
                mstp_net = line.split("=", 1)[1].strip().strip('"').strip("'") or mstp_net
    return f"{mstp_net}:7"


def _model_points_for_device(device_instance: int = BENCH_DEVICE_INSTANCE) -> list[dict[str, Any]]:
    model = ModelService().load()
    device_address = _bench_device_address()
    rows: list[dict[str, Any]] = []
    for pt in model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        try:
            dev_id = int(pt.get("bacnet_device_id") or pt.get("bacnet_device_instance") or 0)
        except (TypeError, ValueError):
            continue
        if dev_id != device_instance:
            continue
        oid = str(pt.get("object_identifier") or "").strip()
        if not oid or "," not in oid:
            continue
        obj_type, obj_inst = oid.split(",", 1)
        rows.append(
            {
                "point_id": str(pt.get("id") or "").strip(),
                "device_instance": str(device_instance),
                "device_address": device_address,
                "object_type": obj_type.strip(),
                "object_instance": obj_inst.strip(),
                "object_name": str(pt.get("description") or pt.get("name") or oid).strip(),
                "description": str(pt.get("description") or "").strip(),
                "units": str(pt.get("units") or "").strip(),
                "brick_class": str(pt.get("brick_type") or "").strip(),
                "brick_tag": str(pt.get("external_id") or pt.get("fdd_input") or "").strip(),
                "enabled": "1",
                "poll_interval_s": str(DEFAULT_POLL_INTERVAL_S),
            }
        )
    return [r for r in rows if r.get("point_id")]


def ensure_bench_5007_discovered(*, poll_interval_s: int = DEFAULT_POLL_INTERVAL_S) -> dict[str, Any]:
    """Seed points_discovered.csv + points.csv from BRICK model for device 5007."""
    points = _model_points_for_device()
    if not points:
        return {"ok": False, "error": f"no model points for BACnet device {BENCH_DEVICE_INSTANCE}"}
    for row in points:
        row["enabled"] = "1"
        row["poll_interval_s"] = str(poll_interval_s)
    return merge_commission_rows(points, enable_poll=True)


def enable_bench_5007_poll(
    *,
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    start_commission: bool = True,
) -> dict[str, Any]:
    """Configure 1-min poll on all four 5007 sensors and optionally start commission agent."""
    discovered = ensure_bench_5007_discovered(poll_interval_s=poll_interval_s)
    if not discovered.get("ok"):
        return discovered

    commission: dict[str, Any] = {"started": False}
    if start_commission:
        commission = ensure_commission_agent()

    try:
        enabled = set_device_poll(
            device_instance=BENCH_DEVICE_INSTANCE,
            enabled=True,
            poll_interval_s=poll_interval_s,
        )
    except ValueError as exc:
        enabled = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "device_instance": BENCH_DEVICE_INSTANCE,
        "poll_interval_s": poll_interval_s,
        "point_count": discovered.get("poll_enabled") or len(_model_points_for_device()),
        "discovered": discovered,
        "enabled": enabled,
        "commission": commission,
        "poll_status": bench_5007_poll_status(),
    }


def commission_agent_pid_path() -> Path:
    return repo_root() / "workspace" / "data" / "commission_agent.pid"


def commission_agent_running() -> bool:
    pid_path = commission_agent_pid_path()
    if not pid_path.is_file():
        code, _ = commission_health(timeout=2.0)
        return code == 200
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    code, _ = commission_health(timeout=2.0)
    return code == 200


def ensure_commission_agent() -> dict[str, Any]:
    """Start bacnet_toolshed commission agent if not already listening on :8767."""
    if commission_agent_running():
        return {"ok": True, "already_running": True, "url": os.environ.get("OPENFDD_BACNET_COMMISSION_URL", "http://127.0.0.1:8767")}

    root = repo_root()
    venv_py = root / ".venv" / "bin" / "python"
    py = str(venv_py if venv_py.is_file() else Path(sys.executable))
    env = os.environ.copy()
    env.setdefault("OPENFDD_REPO_ROOT", str(root))
    env.setdefault("OPENFDD_WORKSPACE_DIR", str(root / "workspace"))
    env.setdefault("OFDD_DESKTOP_DATA_DIR", str(root / "workspace" / "data"))
    env["PYTHONPATH"] = f"{root / 'workspace' / 'api'}:{root}"

    log_path = root / "workspace" / "data" / "commission_agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [py, "-m", "bacnet_toolshed.commission_agent"],
        cwd=str(root),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    commission_agent_pid_path().write_text(str(proc.pid), encoding="utf-8")

    deadline = time.time() + 12.0
    while time.time() < deadline:
        code, payload = commission_health(timeout=2.0)
        if code == 200:
            return {
                "ok": True,
                "started": True,
                "pid": proc.pid,
                "health": payload,
                "log_path": str(log_path),
            }
        time.sleep(0.5)

    return {
        "ok": False,
        "started": True,
        "pid": proc.pid,
        "error": "commission agent started but health check did not pass within 12s",
        "log_path": str(log_path),
    }


def trigger_poll_once() -> dict[str, Any]:
    code, payload = commission_poll_once()
    ingest: dict[str, Any] = {}
    if code == 200:
        try:
            from .bacnet_poll_ingest import ingest_poll_samples_to_feather

            ingest = ingest_poll_samples_to_feather()
        except Exception as exc:
            ingest = {"ok": False, "error": str(exc)[:200]}
    return {
        "ok": code == 200,
        "status_code": code,
        "poll": payload if isinstance(payload, dict) else {"detail": payload},
        "ingest": ingest,
    }


def bench_5007_poll_status() -> dict[str, Any]:
    """Aggregate poll config + commission loop status for bench device 5007."""
    tree = driver_tree()
    dev = next(
        (d for d in tree.get("devices") or [] if int(d.get("device_instance") or 0) == BENCH_DEVICE_INSTANCE),
        None,
    )
    points = dev.get("points") if isinstance(dev, dict) else []
    enabled_pts = [p for p in points or [] if p.get("enabled")]

    code, poll = commission_poll_status(timeout=3.0)
    health_code, health = commission_health(timeout=2.0)

    last_sample_ts = ""
    try:
        from .paths import bacnet_poll_csv
        import csv

        path = bacnet_poll_csv()
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ts = str(row.get("timestamp_utc") or "")
                    if ts >= last_sample_ts:
                        last_sample_ts = ts
    except Exception:
        pass

    return {
        "ok": True,
        "device_instance": BENCH_DEVICE_INSTANCE,
        "device_address": _bench_device_address(),
        "commission_reachable": health_code == 200,
        "commission_health": health if isinstance(health, dict) else {},
        "commission_running": commission_agent_running(),
        "enabled_point_count": len(enabled_pts),
        "poll_interval_s": min(
            (int(p.get("poll_interval_s") or DEFAULT_POLL_INTERVAL_S) for p in enabled_pts),
            default=DEFAULT_POLL_INTERVAL_S,
        )
        if enabled_pts
        else 0,
        "points": [
            {
                "point_id": p.get("point_id"),
                "object_name": p.get("object_name"),
                "enabled": p.get("enabled"),
                "poll_interval_s": p.get("poll_interval_s"),
                "present_value": p.get("present_value"),
            }
            for p in enabled_pts
        ],
        "poll_loop": poll if isinstance(poll, dict) else {"detail": poll, "status_code": code},
        "last_sample_timestamp_utc": last_sample_ts,
        "driver_tree_devices": len(tree.get("devices") or []),
    }
