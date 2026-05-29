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
    bacnet_write,
    perform_who_is,
    point_discovery,
    supervisory_logic_check,
)
from bacnet_toolshed.stack_args import bacnet_argv_from_cfg

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
    return merged


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
        cfg.get("BACNET_NAME", "OpenFddEdge"),
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
            _bacnet_app_cfg_key = cfg_key
        return _bacnet_app


def _bacnet_app_from_cfg(cfg: dict[str, str]) -> Application:
    return _get_bacnet_app(cfg)


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

    async def _inner() -> dict[str, Any]:
        cfg = _cfg()
        app = _bacnet_app_from_cfg(cfg)
        try:
            return await coro_factory(app)
        finally:
            app.close()

    try:
        with log_file.open("w", encoding="utf-8") as log:
            log.write(f"# started {_utc_now()}\n# kind: {kind}\n\n")
            log.flush()
            result = asyncio.run(_inner())
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


def _start_point_discovery(device_instance: int) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]

    async def _run(app: Application) -> dict[str, Any]:
        return await point_discovery(app, device_instance)

    thread = threading.Thread(
        target=_run_async_bacnet_job, args=(job_id, "point_discovery", _run), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "kind": "point_discovery", "device_instance": device_instance}


def _start_supervisory_check(device_instance: int) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]

    async def _run(app: Application) -> dict[str, Any]:
        return await supervisory_logic_check(app, device_instance)

    thread = threading.Thread(
        target=_run_async_bacnet_job, args=(job_id, "supervisory_check", _run), daemon=True
    )
    thread.start()
    return {"job_id": job_id, "kind": "supervisory_check", "device_instance": device_instance}


def _sync_who_is(range_low: int, range_high: int) -> dict[str, Any]:
    cfg = _cfg()

    async def _run(app: Application) -> dict[str, Any]:
        devices = await perform_who_is(app, range_low, range_high)
        return {"devices": devices, "count": len(devices)}

    async def _inner() -> dict[str, Any]:
        app = _bacnet_app_from_cfg(cfg)
        try:
            return await _run(app)
        finally:
            app.close()

    return asyncio.run(_inner())


def _sync_bacnet_write(body: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg()
    required = ("device_instance", "object_identifier", "property_identifier")
    for key in required:
        if key not in body:
            raise ValueError(f"missing {key}")

    async def _run(app: Application) -> dict[str, Any]:
        return await bacnet_write(
            app,
            int(body["device_instance"]),
            str(body["object_identifier"]),
            str(body["property_identifier"]),
            body.get("value"),
            body.get("priority"),
        )

    async def _inner() -> dict[str, Any]:
        app = _bacnet_app_from_cfg(cfg)
        try:
            return await _run(app)
        finally:
            app.close()

    return asyncio.run(_inner())


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
            return _json_response(
                self,
                200,
                {
                    "site_id": cfg.get("SITE_ID"),
                    "building_id": cfg.get("BUILDING_ID"),
                    "bacnet_bind": cfg.get("BACNET_BIND"),
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
            started = _start_point_discovery(int(inst))
            return _json_response(self, 202, started)

        if path == "/api/jobs/supervisory-check":
            inst = body.get("device_instance")
            if inst is None:
                return _json_response(self, 400, {"error": "device_instance required"})
            started = _start_supervisory_check(int(inst))
            return _json_response(self, 202, started)

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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
