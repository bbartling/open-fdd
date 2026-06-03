"""Host OS metrics for the operator dashboard (Linux /proc-first, portable fallbacks)."""

from __future__ import annotations

import os
import platform
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import data_dir


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


def _directory_bytes(path: Path, *, max_depth: int = 4) -> int:
    total = 0
    if not path.exists():
        return 0
    root_depth = len(path.parts)
    for dirpath, _dirnames, filenames in os.walk(path):
        depth = len(Path(dirpath).parts) - root_depth
        if depth > max_depth:
            continue
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


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


def _ollama_process_summary() -> dict[str, Any] | None:
    """Best-effort Ollama process footprint from /proc (optional RAM line on Host Stats)."""
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
        if not comm.startswith("ollama"):
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


def _ollama_payload() -> dict[str, Any]:
    """Ollama status for Host Stats — API reachability matches the Agent chat tab."""
    from . import ollama_client

    health = ollama_client.health()
    proc = _ollama_process_summary()
    chat_timeout = float(os.environ.get("OFDD_OLLAMA_TIMEOUT_S", str(ollama_client.DEFAULT_TIMEOUT_S)))
    payload: dict[str, Any] = {
        "api_ok": health.get("ok") is True,
        "base_url": health.get("base_url"),
        "active_base_url": health.get("base_url") if health.get("ok") else None,
        "tried_urls": health.get("tried_urls") or [],
        "models_installed": health.get("models_installed") or [],
        "configured_model": health.get("configured_model"),
        "configured_ram_tier": health.get("configured_ram_tier") or ollama_client.configured_ram_tier(),
        "gpu_mode": os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu"),
        "health_timeout_s": health.get("health_timeout_s"),
        "chat_timeout_s": chat_timeout,
        "error": health.get("error"),
        "process": proc,
    }
    if proc:
        payload["pid"] = proc.get("pid")
        payload["rss_bytes"] = proc.get("rss_bytes")
        payload["command"] = proc.get("command")
    return payload


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
    storage: dict[str, Any] = {"available": False}
    try:
        data_path = data_dir()
        data_path.mkdir(parents=True, exist_ok=True)
        storage = _disk_for_path(data_path)
        storage["label"] = "Data disk"
        storage["role"] = "data"
        storage["available"] = True
        storage["note"] = "Feather store, rules, and model JSON live here"
        from .feather_store import FeatherStore, feather_max_gib_from_env

        feather_root = data_path / "feather_store"
        store = FeatherStore(root=feather_root)
        storage["feather_bytes"] = store.total_bytes()
        storage["feather_max_gib"] = feather_max_gib_from_env()
        breakdown: list[dict[str, Any]] = [
            {
                "role": "feather",
                "label": "Feather historian",
                "path": str(feather_root),
                "bytes": store.total_bytes(),
            }
        ]
        other_bytes = 0
        for child in data_path.iterdir():
            if child.name == "feather_store":
                continue
            if child.is_file():
                try:
                    other_bytes += child.stat().st_size
                except OSError:
                    continue
            elif child.is_dir():
                other_bytes += _directory_bytes(child, max_depth=3)
        breakdown.append(
            {
                "role": "data_other",
                "label": "Rules, model JSON, FDD results",
                "path": str(data_path),
                "bytes": other_bytes,
            }
        )
        ollama_models = os.environ.get("OLLAMA_MODELS", "").strip() or os.path.expanduser("~/.ollama")
        ollama_path = Path(ollama_models)
        if ollama_path.is_dir():
            breakdown.append(
                {
                    "role": "ollama_models",
                    "label": "Ollama model store",
                    "path": str(ollama_path),
                    "bytes": _directory_bytes(ollama_path, max_depth=5),
                }
            )
        storage["breakdown"] = breakdown
    except OSError:
        pass

    net = _network_totals()
    ollama = _ollama_payload()

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
        "storage": storage,
        "disks": disks,
        "network": net or {"available": False},
        "processes": {"count": _process_count()},
        "ollama": ollama,
    }
