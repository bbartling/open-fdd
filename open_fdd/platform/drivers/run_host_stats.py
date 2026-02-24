#!/usr/bin/env python3
"""
Host and container resource scraper → TimescaleDB.

Reads host memory/load from /proc (mount host's /proc at /host/proc)
and Docker container stats via Docker socket. Writes to host_metrics
and container_metrics for Grafana dashboards.

Usage:
  python tools/run_host_stats.py
  python tools/run_host_stats.py --loop

Config (env): OFDD_DB_DSN, OFDD_HOST_STATS_INTERVAL_SEC (default 60).
"""

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import docker
except ImportError:
    docker = None


def _parse_meminfo(proc_root: str) -> dict | None:
    """Parse /proc/meminfo; return dict with bytes. proc_root = '/host/proc' or '/proc'."""
    path = Path(proc_root) / "meminfo"
    if not path.exists():
        return None
    data = {}
    for line in path.read_text().splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s*kB", line)
        if m:
            data[m.group(1)] = int(m.group(2)) * 1024
    return data


def _parse_loadavg(proc_root: str) -> tuple[float, float, float] | None:
    """Parse /proc/loadavg; return (load_1, load_5, load_15)."""
    path = Path(proc_root) / "loadavg"
    if not path.exists():
        return None
    parts = path.read_text().split()[:3]
    if len(parts) != 3:
        return None
    return float(parts[0]), float(parts[1]), float(parts[2])


def _get_host_metrics(proc_root: str = "/host/proc") -> dict | None:
    """Get host memory and load; use /proc if /host/proc not mounted."""
    for root in [proc_root, "/proc"]:
        mem = _parse_meminfo(root)
        load = _parse_loadavg(root)
        if mem and load:
            return {
                "mem_total_bytes": mem.get("MemTotal", 0),
                "mem_used_bytes": mem.get("MemTotal", 0)
                - mem.get("MemAvailable", mem.get("MemFree", 0)),
                "mem_available_bytes": mem.get("MemAvailable", mem.get("MemFree", 0)),
                "swap_total_bytes": mem.get("SwapTotal", 0),
                "swap_used_bytes": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0),
                "load_1": load[0],
                "load_5": load[1],
                "load_15": load[2],
            }
    return None


def _get_container_metrics() -> list[dict]:
    """Get per-container CPU, memory, PIDs from Docker API."""
    if docker is None:
        return []
    try:
        client = docker.from_env()
        containers = client.containers.list()
        # First snapshot
        snap1 = {}
        for c in containers:
            try:
                snap1[c.id] = c.stats(stream=False)
            except Exception:
                pass
        time.sleep(1)
        rows = []
        for c in containers:
            try:
                s1 = snap1.get(c.id)
                s2 = c.stats(stream=False)
            except Exception:
                s1 = snap1.get(c.id)
                s2 = s1
            if not s2:
                continue
            name = c.name
            cpu = 0.0
            if s1:
                try:
                    c1 = (
                        s1.get("cpu_stats", {}).get("cpu_usage", {}).get("total", 0)
                        or 0
                    )
                    s1_sys = s1.get("cpu_stats", {}).get("system_cpu_usage") or 0
                    c2 = (
                        s2.get("cpu_stats", {}).get("cpu_usage", {}).get("total", 0)
                        or 0
                    )
                    s2_sys = s2.get("cpu_stats", {}).get("system_cpu_usage") or 0
                    cpu_delta = c2 - c1
                    sys_delta = s2_sys - s1_sys
                    if sys_delta and sys_delta > 0:
                        num_cpus = s2.get("cpu_stats", {}).get("online_cpus", 1) or 1
                        cpu = min(100.0, (cpu_delta / sys_delta) * num_cpus * 100)
                except KeyError:
                    pass
                except TypeError:
                    pass
                except ZeroDivisionError:
                    pass
            s = s2
            mem_usage = s.get("memory_stats", {}).get("usage", 0) or 0
            mem_limit = s.get("memory_stats", {}).get("limit") or None
            mem_pct = None
            if mem_limit and mem_limit > 0:
                mem_pct = 100.0 * mem_usage / mem_limit
            net_rx = net_tx = block_read = block_write = None
            nets = s.get("networks", {})
            if nets:
                net_rx = sum(n.get("rx_bytes", 0) for n in nets.values())
                net_tx = sum(n.get("tx_bytes", 0) for n in nets.values())
            blk = s.get("blkio_stats", {}).get("io_service_bytes_recursive", [])
            for e in blk:
                if e.get("op") == "read":
                    block_read = (block_read or 0) + e.get("value", 0)
                elif e.get("op") == "write":
                    block_write = (block_write or 0) + e.get("value", 0)
            pids = s.get("pids_stats", {}).get("current", 0) or 0
            rows.append(
                {
                    "container_name": name,
                    "cpu_pct": round(cpu, 2),
                    "mem_usage_bytes": mem_usage,
                    "mem_limit_bytes": mem_limit,
                    "mem_pct": round(mem_pct, 2) if mem_pct is not None else None,
                    "pids": pids,
                    "net_rx_bytes": net_rx,
                    "net_tx_bytes": net_tx,
                    "block_read_bytes": block_read,
                    "block_write_bytes": block_write,
                }
            )
        return rows
    except Exception as e:
        logging.getLogger("open_fdd.host_stats").warning("Docker stats failed: %s", e)
        return []


def _get_hostname() -> str:
    """Prefer host's hostname from /host/proc/sys/kernel/hostname."""
    for p in ["/host/proc/sys/kernel/hostname", "/proc/sys/kernel/hostname"]:
        if Path(p).exists():
            return Path(p).read_text().strip()
    return os.environ.get("HOSTNAME", "unknown")


def _write_metrics(host: dict | None, containers: list[dict]) -> None:
    """Bulk insert into host_metrics and container_metrics."""
    from datetime import datetime

    from psycopg2.extras import execute_values

    from open_fdd.platform.database import get_conn

    now = datetime.utcnow()
    hostname = _get_hostname()

    with get_conn() as conn:
        with conn.cursor() as cur:
            if host:
                cur.execute(
                    """
                    INSERT INTO host_metrics (ts, hostname, mem_total_bytes, mem_used_bytes, mem_available_bytes,
                        swap_total_bytes, swap_used_bytes, load_1, load_5, load_15)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now,
                        hostname,
                        host["mem_total_bytes"],
                        host["mem_used_bytes"],
                        host["mem_available_bytes"],
                        host["swap_total_bytes"],
                        host["swap_used_bytes"],
                        host["load_1"],
                        host["load_5"],
                        host["load_15"],
                    ),
                )
            if containers:
                rows = [
                    (
                        now,
                        r["container_name"],
                        r["cpu_pct"],
                        r["mem_usage_bytes"],
                        r["mem_limit_bytes"],
                        r["mem_pct"],
                        r["pids"],
                        r["net_rx_bytes"],
                        r["net_tx_bytes"],
                        r["block_read_bytes"],
                        r["block_write_bytes"],
                    )
                    for r in containers
                ]
                execute_values(
                    cur,
                    """
                    INSERT INTO container_metrics (ts, container_name, cpu_pct, mem_usage_bytes, mem_limit_bytes,
                        mem_pct, pids, net_rx_bytes, net_tx_bytes, block_read_bytes, block_write_bytes)
                    VALUES %s
                    """,
                    rows,
                    page_size=50,
                )
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Host/container stats → TimescaleDB")
    parser.add_argument("--loop", action="store_true", help="Run every N seconds")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("open_fdd.host_stats")

    interval = int(os.environ.get("OFDD_HOST_STATS_INTERVAL_SEC", "60"))

    def _run() -> int:
        try:
            host = _get_host_metrics()
            containers = _get_container_metrics()
            _write_metrics(host, containers)
            log.info(
                "Wrote host=%s containers=%d", "ok" if host else "skip", len(containers)
            )
            return 0
        except Exception as e:
            log.exception("Stats run failed: %s", e)
            return 1

    if args.loop:
        log.info("Host stats loop: every %d s", interval)
        while True:
            _run()
            time.sleep(interval)
    else:
        return _run()


if __name__ == "__main__":
    sys.exit(main())
