"""Host OS metrics for the operator dashboard (Linux /proc-first, portable fallbacks)."""

from __future__ import annotations

import os
import platform
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import data_dir, repo_root, workspace_dir


def _bytes_from_proc_value(raw: str) -> int:
    """Parse kB lines from /proc/meminfo."""
    return int(raw.strip().split()[0]) * 1024


def _read_linux_meminfo() -> dict[str, int] | None:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        try:
            out[key.strip()] = _bytes_from_proc_value(val)
        except (IndexError, ValueError):
            continue
    return out or None


def _read_cpu_times() -> tuple[int, int] | None:
    path = Path("/proc/stat")
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()[1:]
        if len(parts) < 4:
            return None
        nums = [int(x) for x in parts[:10]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)
        return total, idle
    return None


def _cpu_usage_percent(sample_interval: float = 0.08) -> float | None:
    first = _read_cpu_times()
    if first is None:
        return None
    time.sleep(max(0.02, sample_interval))
    second = _read_cpu_times()
    if second is None:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)), 1)


def _logical_cpu_count() -> int:
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _load_average() -> tuple[float, float, float] | None:
    try:
        one, five, fifteen = os.getloadavg()
        return round(one, 2), round(five, 2), round(fifteen, 2)
    except (AttributeError, OSError):
        return None


def _uptime_seconds() -> float | None:
    path = Path("/proc/uptime")
    if path.is_file():
        try:
            return round(float(path.read_text().split()[0]), 1)
        except (IndexError, ValueError):
            pass
    return None


def _disk_for_path(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    used = usage.used
    total = usage.total
    pct = round((used / total) * 100.0, 1) if total else 0.0
    return {
        "label": str(path),
        "path": str(path),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": usage.free,
        "percent_used": pct,
    }


def _network_totals() -> dict[str, int] | None:
    path = Path("/proc/net/dev")
    if not path.is_file():
        return None
    rx = tx = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[2:]:
        if ":" not in line:
            continue
        _, stats = line.split(":", 1)
        cols = stats.split()
        if len(cols) < 16:
            continue
        iface = line.split(":", 1)[0].strip()
        if iface == "lo":
            continue
        try:
            rx += int(cols[0])
            tx += int(cols[8])
        except ValueError:
            continue
    return {"rx_bytes": rx, "tx_bytes": tx}


def _process_count() -> int | None:
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    try:
        return sum(1 for p in proc.iterdir() if p.name.isdigit())
    except OSError:
        return None


def _ollama_summary() -> dict[str, Any] | None:
    """Best-effort Ollama process footprint when local AI is running."""
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    best: dict[str, Any] | None = None
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip("\x00")
        except OSError:
            continue
        if comm != "ollama":
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rss_kb = 0
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                break
        candidate = {
            "pid": int(entry.name),
            "command": cmdline[:120] or comm,
            "rss_bytes": rss_kb * 1024,
        }
        if cmdline.startswith("ollama serve") or " serve" in cmdline:
            return candidate
        best = candidate
    return best


def _memory_payload(meminfo: dict[str, int] | None) -> dict[str, Any]:
    if not meminfo:
        return {"available": False}
    total = meminfo.get("MemTotal", 0)
    available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    used = max(0, total - available)
    pct = round((used / total) * 100.0, 1) if total else 0.0
    return {
        "available": True,
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent_used": pct,
    }


def _swap_payload(meminfo: dict[str, int] | None) -> dict[str, Any]:
    if not meminfo:
        return {"available": False}
    total = meminfo.get("SwapTotal", 0)
    free = meminfo.get("SwapFree", 0)
    used = max(0, total - free)
    pct = round((used / total) * 100.0, 1) if total else 0.0
    return {
        "available": True,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent_used": pct,
    }


def collect_host_stats(*, cpu_sample_interval: float = 0.08) -> dict[str, Any]:
    meminfo = _read_linux_meminfo()
    load = _load_average()
    cpu_pct = _cpu_usage_percent(cpu_sample_interval)

    cpu: dict[str, Any] = {
        "logical_cores": _logical_cpu_count(),
        "usage_percent": cpu_pct,
    }
    if load:
        cpu["load_1"] = load[0]
        cpu["load_5"] = load[1]
        cpu["load_15"] = load[2]

    disks: list[dict[str, Any]] = []
    for label, path in (
        ("repo", repo_root()),
        ("workspace", workspace_dir()),
        ("data", data_dir()),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
            disk = _disk_for_path(path)
            disk["label"] = label
            disks.append(disk)
        except OSError:
            continue

    root_disk = None
    try:
        root_disk = _disk_for_path(Path("/"))
        root_disk["label"] = "root (/)"
    except OSError:
        pass
    if root_disk and not any(d["path"] == "/" for d in disks):
        disks.insert(0, root_disk)

    net = _network_totals()
    ollama = _ollama_summary()

    return {
        "ok": True,
        "collected_at": datetime.now(UTC).isoformat(),
        "host": {
            "hostname": platform.node() or "unknown",
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "uptime_seconds": _uptime_seconds(),
        },
        "cpu": cpu,
        "memory": _memory_payload(meminfo),
        "swap": _swap_payload(meminfo),
        "disks": disks,
        "network": net or {"available": False},
        "processes": {"count": _process_count()},
        "ollama": ollama,
    }
