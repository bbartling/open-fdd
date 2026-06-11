"""Read/write BACnet bind address in commission.env and restart commission service."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from bacnet_toolshed.nic_bind import list_host_interfaces, normalize_bacnet_bind

from .ops_logs import _compose_dir
from .paths import workspace_dir


def commission_env_path() -> Path:
    return workspace_dir() / "bacnet" / "commissioning" / "commission.env"


def read_bacnet_bind() -> str:
    path = commission_env_path()
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("BACNET_BIND="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def write_bacnet_bind(bind: str, *, previous: str | None = None) -> dict[str, Any]:
    """Update BACNET_BIND= in commission.env; stores previous bind in .bak line comment."""
    normalized = normalize_bacnet_bind(bind)
    path = commission_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    replaced = False
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith("BACNET_BIND="):
                if previous and not any(l.startswith("# PREVIOUS_BACNET_BIND=") for l in lines):
                    lines.append(f"# PREVIOUS_BACNET_BIND={previous}")
                lines.append(f"BACNET_BIND={normalized}")
                replaced = True
            else:
                lines.append(raw)
    if not replaced:
        if previous:
            lines.append(f"# PREVIOUS_BACNET_BIND={previous}")
        lines.append(f"BACNET_BIND={normalized}")
    if not lines:
        lines = [f"BACNET_BIND={normalized}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "bacnet_bind": normalized, "path": str(path)}


def restore_previous_bacnet_bind() -> dict[str, Any]:
    path = commission_env_path()
    if not path.is_file():
        return {"ok": False, "error": "commission.env missing"}
    prev = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#\s*PREVIOUS_BACNET_BIND=(.+)", raw.strip())
        if m:
            prev = m.group(1).strip()
    if not prev:
        return {"ok": False, "error": "no previous bind stored"}
    current = read_bacnet_bind()
    return write_bacnet_bind(prev, previous=current)


def restart_bacnet_commission() -> dict[str, Any]:
    """Restart BACnet commission container/service only."""
    compose = _compose_dir()
    if compose and os.environ.get("OFDD_OPS_DOCKER_DISABLED", "").strip().lower() not in {"1", "true", "yes"}:
        try:
            proc = subprocess.run(
                ["docker", "compose", "restart", "commission"],
                cwd=str(compose),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            return {
                "ok": proc.returncode == 0,
                "method": "docker_compose",
                "compose_dir": str(compose),
                "stdout": (proc.stdout or "")[-2000:],
                "stderr": (proc.stderr or "")[-2000:],
                "exit_code": proc.returncode,
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "method": "docker_compose", "error": str(exc)}
    return {
        "ok": False,
        "method": "none",
        "error": "docker compose dir not found — restart commission container manually",
    }


def interfaces_payload() -> dict[str, Any]:
    ifaces = list_host_interfaces()
    current = read_bacnet_bind()
    host = current.split("/")[0].split(":")[0] if current else ""
    return {"ok": True, "current_bind": current, "current_host": host, "interfaces": ifaces}
