"""Lightweight HTTP agent for BACnet discover jobs on the OT edge (no MQTT)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser

from bacnet_toolshed.bacnet_ops import (
    BacnetOpsError,
    bacnet_read,
    bacnet_read_multiple,
    bacnet_write,
    perform_who_is,
    point_discovery,
    read_point_priority_array,
    supervisory_logic_check,
)
from bacnet_toolshed.models import (
    ReadMultiplePropertiesRequestWrapper,
    ReadPriorityArrayRequest,
    SingleReadRequest,
    WritePropertyRequest,
)
from bacnet_toolshed.fdd_fault_count import active_fdd_fault_count
from bacnet_toolshed.server_points import (
    install_openfdd_server_points,
    server_points_snapshot,
    update_openfdd_server_points,
)
from bacnet_toolshed.stack_args import bacnet_argv_from_cfg, discover_timeout_s, route_discovery_kwargs
from bacnet_toolshed.bacnet_io_priority import BacnetPriority, init_loop_state, run_bacnet_op
from bacnet_toolshed.bacnet_override_scan_loop import (
    run_override_scan_cycle,
    start_override_scan_loop,
)
from bacnet_toolshed.bacnet_poll_loop import (
    enabled_point_count,
    last_poll_status,
    poll_interval_s,
    run_poll_cycle,
    start_poll_loop,
)
from bacnet_toolshed.override_registry import scan_status as override_scan_status

from bacnet_toolshed.nic_bind import resolve_commission_cfg
from bacnet_toolshed.paths import (
    commissioning_dir,
    default_points_discovered,
    default_points_enabled,
    jobs_dir,
    repo_root,
)

TOKEN = os.environ.get("OPENFDD_BACNET_COMMISSION_TOKEN", "").strip()
BIND_HOST = os.environ.get("OPENFDD_BACNET_COMMISSION_BIND", "127.0.0.1")
BIND_PORT = int(os.environ.get("OPENFDD_BACNET_COMMISSION_PORT", "8767"))
ENV_FILE = commissioning_dir() / "commission.env"

_bacnet_app: Application | None = None
_bacnet_app_cfg_key: tuple[tuple[str, str], ...] | None = None
_bacnet_app_lock = threading.Lock()
_bacnet_op_lock = threading.Lock()
_bacnet_serial_lock: asyncio.Lock | None = None
_bacnet_loop: asyncio.AbstractEventLoop | None = None
_bacnet_loop_ready = threading.Event()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return out
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _cfg() -> dict[str, str]:
    merged = _load_env_file()
    for key in (
        "SITE_ID",
        "BUILDING_ID",
        "BACNET_BIND",
        "BACNET_NAME",
        "BACNET_INSTANCE",
        "DISCOVER_LOW",
        "DISCOVER_HIGH",
        "ROUTER_IP",
        "MSTP_NET",
        "BACNET_NETWORK",
        "DISCOVER_TIMEOUT",
    ):
        env_val = os.environ.get(key, "").strip()
        if env_val:
            merged[key] = env_val
    return resolve_commission_cfg(merged)


def _python() -> str:
    venv = repo_root() / ".venv" / "bin" / "python"
    return str(venv if venv.is_file() else sys.executable)


def _discover_cmd(cfg: dict[str, str], output: Path) -> list[str]:
    low = cfg.get("DISCOVER_LOW", "1")
    high = cfg.get("DISCOVER_HIGH", "4194303")
    cmd = [
        _python(),
        "-m",
        "bacnet_toolshed.discover",
        str(low),
        str(high),
        "-o",
        str(output),
        "--site-id",
        cfg.get("SITE_ID", "site"),
        "--building-id",
        cfg.get("BUILDING_ID", "building"),
        "--name",
        cfg.get("BACNET_NAME", "OpenFDD"),
        "--instance",
        cfg.get("BACNET_INSTANCE", "599999"),
        "--address",
        cfg.get("BACNET_BIND", "0.0.0.0/24:47808"),
    ]
    router = cfg.get("ROUTER_IP", "").strip()
    if router:
        cmd.extend(
            [
                "--route-aware",
                "--network",
                cfg.get("BACNET_NETWORK", "1"),
                "--router-ip",
                router,
                "--mstp-net",
                cfg.get("MSTP_NET", "2000"),
                "--timeout",
                cfg.get("DISCOVER_TIMEOUT", "20"),
            ]
        )
    return cmd


def _job_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def _log_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.log"


def _list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    root = jobs_dir()
    if not root.is_dir():
        return []
    jobs: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        if len(jobs) >= limit:
            break
    return jobs


def _read_tail(path: Path, max_lines: int = 80) -> str:
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def _run_job(job_id: str, kind: str, cmd: list[str]) -> None:
    log_file = _log_path(job_id)
    meta = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "cmd": cmd,
        "started_at": _utc_now(),
        "finished_at": "",
        "exit_code": None,
    }
    _job_path(job_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    jobs_dir().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root())
    env.setdefault("OPENFDD_REPO_ROOT", str(repo_root()))
    try:
        with log_file.open("w", encoding="utf-8") as log:
            log.write(f"# started {_utc_now()}\n# cmd: {' '.join(cmd)}\n\n")
            log.flush()
            proc = subprocess.run(
                cmd,
                cwd=str(repo_root()),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        meta["status"] = "ok" if proc.returncode == 0 else "failed"
        meta["finished_at"] = _utc_now()
        meta["exit_code"] = proc.returncode
    except Exception as exc:
        meta["status"] = "failed"
        meta["finished_at"] = _utc_now()
        meta["exit_code"] = -1
        meta["error"] = str(exc)
    finally:
        _job_path(job_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _start_discover(range_low: str | None, range_high: str | None) -> dict[str, Any]:
    cfg = _cfg()
    if range_low:
        cfg["DISCOVER_LOW"] = range_low
    if range_high:
        cfg["DISCOVER_HIGH"] = range_high
    job_id = uuid.uuid4().hex[:12]
    commissioning_dir().mkdir(parents=True, exist_ok=True)
    output = default_points_discovered()
    cmd = _discover_cmd(cfg, output)
    thread = threading.Thread(target=_run_job, args=(job_id, "discover", cmd), daemon=True)
    thread.start()
    return {"job_id": job_id, "kind": "discover", "output": str(output)}


def _get_bacnet_app(cfg: dict[str, str]) -> Application:
    global _bacnet_app, _bacnet_app_cfg_key
    cfg_key = tuple(sorted((k, str(v)) for k, v in cfg.items()))
    with _bacnet_app_lock:
        if _bacnet_app is None or _bacnet_app_cfg_key != cfg_key:
            parser = SimpleArgumentParser()
            _bacnet_app = Application.from_args(parser.parse_args(bacnet_argv_from_cfg(cfg)))
            install_openfdd_server_points(_bacnet_app)
            _bacnet_app_cfg_key = cfg_key
        return _bacnet_app


def _bacnet_app_from_cfg(cfg: dict[str, str]) -> Application:
    return _get_bacnet_app(cfg)


def _bacnet_loop_thread_main() -> None:
    global _bacnet_loop, _bacnet_serial_lock
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _bacnet_loop = loop
    _bacnet_serial_lock = asyncio.Lock()
    init_loop_state(_bacnet_serial_lock)
    _bacnet_loop_ready.set()
    loop.run_forever()


def _ensure_bacnet_loop() -> asyncio.AbstractEventLoop:
    global _bacnet_loop
    if _bacnet_loop is not None and _bacnet_loop.is_running():
        return _bacnet_loop
    with _bacnet_app_lock:
        if _bacnet_loop is not None and _bacnet_loop.is_running():
            return _bacnet_loop
        _bacnet_loop_ready.clear()
        thread = threading.Thread(target=_bacnet_loop_thread_main, name="bacnet-io", daemon=True)
        thread.start()
        if not _bacnet_loop_ready.wait(timeout=15):
            raise RuntimeError("BACnet I/O loop failed to start")
        if _bacnet_loop is None:
            raise RuntimeError("BACnet I/O loop missing after start")
        return _bacnet_loop


def _get_bacnet_app_locked() -> Application:
    with _bacnet_op_lock:
        return _bacnet_app_from_cfg(_cfg())


def _run_bacnet_sync(
    coro_factory,
    *,
    priority: BacnetPriority = BacnetPriority.INTERACTIVE,
    timeout: float = 180.0,
) -> Any:
    """Run BACnet coroutine on the dedicated loop; interactive ops preempt background scrape."""
    loop = _ensure_bacnet_loop()

    async def _inner() -> Any:
        if _bacnet_serial_lock is None:
            raise RuntimeError("BACnet serial lock missing")
        return await run_bacnet_op(
            coro_factory,
            _get_bacnet_app_locked,
            priority=priority,
        )

    future = asyncio.run_coroutine_threadsafe(_inner(), loop)
    return future.result(timeout=timeout)


def _run_bacnet_background(coro_factory, timeout: float = 180.0) -> Any:
    return _run_bacnet_sync(coro_factory, priority=BacnetPriority.BACKGROUND, timeout=timeout)


def _run_bacnet_override_scan(coro_factory, timeout: float = 900.0) -> Any:
    """Supervisory override scans may read many priority arrays — allow up to 15 min."""
    return _run_bacnet_sync(coro_factory, priority=BacnetPriority.BACKGROUND, timeout=timeout)


def _run_async_bacnet_job(job_id: str, kind: str, coro_factory) -> None:
    log_file = _log_path(job_id)
    meta = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "started_at": _utc_now(),
        "finished_at": "",
        "exit_code": None,
    }
    _job_path(job_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    jobs_dir().mkdir(parents=True, exist_ok=True)

    try:
        with log_file.open("w", encoding="utf-8") as log:
            log.write(f"# started {_utc_now()}\n# kind: {kind}\n\n")
            log.flush()
            result = _run_bacnet_sync(coro_factory)
            log.write(json.dumps(result, indent=2))
        meta["status"] = "ok"
        meta["finished_at"] = _utc_now()
        meta["exit_code"] = 0
        meta["result"] = result
    except Exception as exc:
        meta["status"] = "failed"
        meta["finished_at"] = _utc_now()
        meta["exit_code"] = 1
        meta["error"] = str(exc)
        with log_file.open("a", encoding="utf-8") as log:
            log.write(f"\nERROR: {exc}\n")
    finally:
        _job_path(job_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _start_point_discovery(device_instance: int, device_address: str = "") -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    addr = device_address.strip()

    async def _run(app: Application) -> dict[str, Any]:
        return await point_discovery(
            app,
            device_instance,
            device_address=addr or None,
        )

    thread = threading.Thread(
        target=_run_async_bacnet_job, args=(job_id, "point_discovery", _run), daemon=True
    )
    thread.start()
    out: dict[str, Any] = {
        "job_id": job_id,
        "kind": "point_discovery",
        "device_instance": device_instance,
    }
    if addr:
        out["device_address"] = addr
    return out


def _start_supervisory_check(device_instance: int, device_address: str = "") -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    addr = device_address.strip()

    async def _run(app: Application) -> dict[str, Any]:
        return await supervisory_logic_check(
            app,
            device_instance,
            device_address=addr or None,
        )

    thread = threading.Thread(
        target=_run_async_bacnet_job, args=(job_id, "supervisory_check", _run), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "kind": "supervisory_check", "device_instance": device_instance}


def _sync_who_is(range_low: int, range_high: int) -> dict[str, Any]:
    cfg = _cfg()
    route = route_discovery_kwargs(cfg)

    async def _run(app: Application) -> dict[str, Any]:
        if route:
            from bacnet_toolshed.discover_lib import collect_i_ams

            i_ams = await collect_i_ams(
                app,
                range_low,
                range_high,
                router_ip=str(route["router_ip"]),
                mstp_net=int(route["mstp_net"]),
                timeout=discover_timeout_s(cfg),
                local_too=bool(route.get("local_too", False)),
            )
            devices = []
            for i_am in i_ams or []:
                device_address = i_am.pduSource
                device_identifier = i_am.iAmDeviceIdentifier
                devices.append(
                    {
                        "i-am-device-identifier": str(device_identifier),
                        "device-address": str(device_address),
                        "max-apdu-length-accepted": i_am.maxAPDULengthAccepted,
                        "segmentation-supported": str(i_am.segmentationSupported),
                        "vendor-id": i_am.vendorID,
                    }
                )
            return {"devices": devices, "count": len(devices)}
        devices = await perform_who_is(app, range_low, range_high)
        return {"devices": devices, "count": len(devices)}

    return _run_bacnet_sync(_run)


def _sync_bacnet_write(body: dict[str, Any]) -> dict[str, Any]:
    req = WritePropertyRequest.model_validate(body)

    async def _run(app: Application) -> dict[str, Any]:
        return await bacnet_write(
            app,
            req.device_instance,
            req.object_identifier,
            req.property_identifier,
            req.value,
            req.priority,
        )

    return _run_bacnet_sync(_run)


def _sync_bacnet_read(body: dict[str, Any]) -> dict[str, Any]:
    req = SingleReadRequest.model_validate(body)

    async def _run(app: Application) -> dict[str, Any]:
        addr = str(req.device_address or "").strip() or None
        return await bacnet_read(
            app,
            req.device_instance,
            req.object_identifier,
            req.property_identifier,
            device_address=addr,
        )

    return _run_bacnet_sync(_run)


def _sync_bacnet_read_multiple(body: dict[str, Any]) -> dict[str, Any]:
    req = ReadMultiplePropertiesRequestWrapper.model_validate(body)
    requests = [(r.object_identifier, r.property_identifier) for r in req.requests]

    async def _run(app: Application) -> dict[str, Any]:
        addr = str(req.device_address or "").strip() or None
        return await bacnet_read_multiple(app, req.device_instance, requests, device_address=addr)

    return _run_bacnet_sync(_run)


def _sync_read_priority_array(body: dict[str, Any]) -> dict[str, Any]:
    req = ReadPriorityArrayRequest.model_validate(body)

    async def _run(app: Application) -> dict[str, Any]:
        addr = str(req.device_address or "").strip() or None
        return await read_point_priority_array(
            app, req.device_instance, req.object_identifier, device_address=addr
        )

    return _run_bacnet_sync(_run)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _unauthorized(handler: BaseHTTPRequestHandler) -> None:
    _json_response(handler, 401, {"error": "missing or invalid X-Commission-Token"})


class CommissionAgentHandler(BaseHTTPRequestHandler):
    server_version = "OpenFDD-BacnetToolshed/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        return self.headers.get("X-Commission-Token", "").strip() == TOKEN

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        if not self._authorized():
            return _unauthorized(self)
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/health":
            return _json_response(
                self,
                200,
                {
                    "ok": True,
                    "repo_root": str(repo_root()),
                    "commissioning_dir": str(commissioning_dir()),
                    "time": _utc_now(),
                    "auth": bool(TOKEN),
                },
            )

        if path == "/api/status":
            cfg = _cfg()
            pd = default_points_discovered()
            pe = default_points_enabled()
            running = [j for j in _list_jobs(50) if j.get("status") == "running"]
            devices_discovered = 0
            if pd.is_file():
                try:
                    import csv

                    seen: set[str] = set()
                    with pd.open(newline="", encoding="utf-8") as fh:
                        for row in csv.DictReader(fh):
                            inst = str(row.get("device_instance") or "").strip()
                            if inst:
                                seen.add(inst)
                    devices_discovered = len(seen)
                except OSError:
                    devices_discovered = 0
            poll_rows = 0
            poll_csv = repo_root() / "workspace" / "bacnet" / "polls" / "samples.csv"
            if poll_csv.is_file():
                try:
                    import csv

                    with poll_csv.open(newline="", encoding="utf-8") as fh:
                        poll_rows = sum(1 for _ in csv.DictReader(fh))
                except OSError:
                    poll_rows = 0
            fault_count = active_fdd_fault_count(repo_root())
            update_openfdd_server_points(
                poll_rows=poll_rows,
                devices_discovered=devices_discovered,
                active_fault_count=fault_count,
                commission_ok=True,
                bridge_ok=True,
            )
            return _json_response(
                self,
                200,
                {
                    "site_id": cfg.get("SITE_ID"),
                    "building_id": cfg.get("BUILDING_ID"),
                    "bacnet_bind": cfg.get("BACNET_BIND"),
                    "bacnet_instance": cfg.get("BACNET_INSTANCE", "599999"),
                    "bacnet_name": cfg.get("BACNET_NAME", "OpenFDD"),
                    "server_points": server_points_snapshot(),
                    "discover_range": [
                        cfg.get("DISCOVER_LOW", "1"),
                        cfg.get("DISCOVER_HIGH", "4194303"),
                    ],
                    "files": {
                        "points_discovered": pd.is_file(),
                        "points_csv": pe.is_file(),
                    },
                    "jobs_running": len(running),
                    "last_jobs": _list_jobs(5),
                },
            )

        if path == "/api/bacnet/server/points":
            return _json_response(
                self,
                200,
                {"ok": True, "points": server_points_snapshot()},
            )

        if path == "/api/bacnet/poll/status":
            return _json_response(
                self,
                200,
                {
                    "ok": True,
                    "enabled_points": enabled_point_count(),
                    "interval_s": poll_interval_s(),
                    **last_poll_status(),
                },
            )

        if path == "/api/bacnet/overrides/status":
            return _json_response(self, 200, override_scan_status())

        if path == "/api/jobs":
            return _json_response(self, 200, {"jobs": _list_jobs(30)})

        if path.startswith("/api/jobs/"):
            job_id = path.split("/")[-1]
            meta_path = _job_path(job_id)
            if not meta_path.is_file():
                return _json_response(self, 404, {"error": "job not found"})
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["log_tail"] = _read_tail(_log_path(job_id))
            return _json_response(self, 200, meta)

        return _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return _unauthorized(self)
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_json()

        if path == "/api/jobs/discover":
            started = _start_discover(body.get("range_low"), body.get("range_high"))
            return _json_response(self, 202, started)

        if path == "/api/jobs/point-discovery":
            inst = body.get("device_instance")
            if inst is None:
                return _json_response(self, 400, {"error": "device_instance required"})
            try:
                device_instance = int(inst)
            except (TypeError, ValueError):
                return _json_response(self, 400, {"error": "invalid device_instance"})
            addr = str(body.get("device_address") or "").strip()
            started = _start_point_discovery(device_instance, device_address=addr)
            return _json_response(self, 202, started)

        if path == "/api/jobs/supervisory-check":
            inst = body.get("device_instance")
            if inst is None:
                return _json_response(self, 400, {"error": "device_instance required"})
            addr = str(body.get("device_address") or "").strip()
            started = _start_supervisory_check(int(inst), device_address=addr)
            return _json_response(self, 202, started)

        if path == "/api/bacnet/poll/once":
            result = run_poll_cycle(_run_bacnet_background)
            return _json_response(self, 200, {"ok": bool(result.get("ok")), **result})

        if path == "/api/bacnet/overrides/scan-once":
            result = run_override_scan_cycle(_run_bacnet_override_scan)
            return _json_response(self, 200, result)

        if path == "/api/bacnet/whois":
            low = int(body.get("range_low", _cfg().get("DISCOVER_LOW", 1)))
            high = int(body.get("range_high", _cfg().get("DISCOVER_HIGH", 4194303)))
            try:
                result = _sync_who_is(low, high)
                return _json_response(self, 200, result)
            except Exception as exc:
                return _json_response(self, 500, {"error": str(exc)})

        if path == "/api/bacnet/write":
            try:
                result = _sync_bacnet_write(body)
                return _json_response(self, 200, result)
            except BacnetOpsError as exc:
                return _json_response(self, 400, {"error": str(exc), "data": exc.data})
            except Exception as exc:
                return _json_response(self, 500, {"error": str(exc)})

        if path == "/api/bacnet/read":
            try:
                result = _sync_bacnet_read(body)
                return _json_response(self, 200, result)
            except BacnetOpsError as exc:
                return _json_response(self, 400, {"error": str(exc), "data": exc.data})
            except Exception as exc:
                return _json_response(self, 500, {"error": str(exc)})

        if path == "/api/bacnet/read-multiple":
            try:
                result = _sync_bacnet_read_multiple(body)
                return _json_response(self, 200, result)
            except BacnetOpsError as exc:
                return _json_response(self, 400, {"error": str(exc), "data": exc.data})
            except Exception as exc:
                return _json_response(self, 500, {"error": str(exc)})

        if path == "/api/bacnet/priority-array":
            try:
                result = _sync_read_priority_array(body)
                return _json_response(self, 200, result)
            except BacnetOpsError as exc:
                return _json_response(self, 400, {"error": str(exc), "data": exc.data})
            except Exception as exc:
                return _json_response(self, 500, {"error": str(exc)})

        return _json_response(self, 404, {"error": "not found"})


def main() -> int:
    commissioning_dir().mkdir(parents=True, exist_ok=True)
    jobs_dir().mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), CommissionAgentHandler)
    print(
        f"Open-FDD BACnet toolshed agent on http://{BIND_HOST}:{BIND_PORT} "
        f"(commissioning={commissioning_dir()}, auth={'on' if TOKEN else 'off'})",
        flush=True,
    )
    cfg = _cfg()
    print(
        f"BACnet stack: name={cfg.get('BACNET_NAME')} instance={cfg.get('BACNET_INSTANCE')} "
        f"bind={cfg.get('BACNET_BIND')}",
        flush=True,
    )
    start_poll_loop(_run_bacnet_background)
    start_override_scan_loop(_run_bacnet_override_scan)
    print(
        f"BACnet poll loop started (enabled points={enabled_point_count()}, interval={poll_interval_s()}s)",
        flush=True,
    )
    ostat = override_scan_status()
    print(
        f"BACnet override scan loop started (devices={ostat.get('device_count')}, "
        f"interval={ostat.get('scan_interval_s')}s, operator_priority=P{ostat.get('operator_priority')})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
