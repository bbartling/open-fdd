#!/usr/bin/env python3
"""Emit read-only host/container JSON for Acme edge (run locally or over SSH)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def collect() -> dict:
    home = Path.home()
    compose = home / "open-fdd" / "docker-compose.yml"
    data: dict = {
        "probe_at": datetime.now(timezone.utc).isoformat(),
        "hostname": _run("hostname -s") or _run("hostname"),
        "compose_file": str(compose) if compose.is_file() else None,
        "services": [],
        "exited_openfdd": [],
        "disk_usage_percent": None,
        "mem_available_mb": None,
        "load_average": _run("uptime | sed 's/.*load average: //'"),
        "max_restart_count": 0,
    }
    if _run("command -v docker"):
        data["docker_ps"] = _run("docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}'")
        exited = [
            x
            for x in _run("docker ps -a --filter status=exited --format '{{.Names}}'").splitlines()
            if "openfdd" in x.lower()
        ]
        data["exited_openfdd"] = exited
        if compose.is_file():
            lines = _run(f"docker compose -f {compose} ps --format json")
            for line in lines.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                svc = row.get("Service") or row.get("Name") or ""
                data["services"].append(
                    {"service": svc, "state": row.get("State"), "image": row.get("Image")}
                )
    df = _run(f"df -P {home}/open-fdd 2>/dev/null | awk 'NR==2{{gsub(/%/,\"\",$5); print $5}}'")
    if df:
        try:
            data["disk_usage_percent"] = float(df)
        except ValueError:
            pass
    mem = _run("free -m | awk '/^Mem:/{print $7}'")
    if mem:
        try:
            data["mem_available_mb"] = int(mem)
        except ValueError:
            pass
    return data


def main() -> int:
    print(json.dumps(collect(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
