"""Central validation orchestration (read-only toward edges)."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from portfolio.central.edge_probes import validate_edge_readonly
from portfolio.central.job_store import append_cycle, create_job, load_job, save_job
from portfolio.central.registry import site_config_for, touch_site
from portfolio.collector.collector import collect_site


def run_one_off_validation(
    site_id: str,
    *,
    sites_path: Path | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    cfg = site_config_for(site_id, sites_path=sites_path)
    result = validate_edge_readonly(cfg)
    touch_site(
        site_id,
        validation=True,
        traffic=str(result.get("traffic") or ""),
        error="; ".join(result.get("errors") or []) if not result.get("ok") else "",
        data_dir=data_dir,
    )
    return result


def run_validation_plan(
    site_id: str,
    *,
    interval_hours: float = 2.0,
    duration_hours: float = 24.0,
    sleep_seconds: float = 0.0,
    sites_path: Path | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Run wall-clock spaced validation cycles (sleep_seconds=0 for CI try-out)."""
    cycles = max(1, int(math.ceil(duration_hours / interval_hours)))
    job = create_job(
        site_id=site_id,
        plan="scheduled",
        interval_hours=interval_hours,
        duration_hours=duration_hours,
        data_dir=data_dir,
    )
    job_id = str(job["id"])
    job["status"] = "running"
    save_job(job, data_dir=data_dir)

    cfg = site_config_for(site_id, sites_path=sites_path)
    for n in range(1, cycles + 1):
        cycle_result = validate_edge_readonly(cfg)
        cycle = {
            "cycle": n,
            "ok": cycle_result.get("ok"),
            "errors": cycle_result.get("errors"),
            "checks": {
                k: {"ok": v.get("ok") if isinstance(v, dict) else v}
                for k, v in (cycle_result.get("checks") or {}).items()
            },
            "final": n == cycles,
        }
        append_cycle(job_id, cycle, data_dir=data_dir)
        if n < cycles and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    touch_site(
        site_id,
        validation=True,
        traffic=str(cycle_result.get("traffic") or ""),
        error="; ".join(cycle_result.get("errors") or []) if not cycle_result.get("ok") else "",
        data_dir=data_dir,
    )
    return load_job(job_id, data_dir=data_dir)


def collect_and_validate(
    site_id: str,
    *,
    sites_path: Path | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    cfg = site_config_for(site_id, sites_path=sites_path)
    collect_out: dict[str, Any] = {"ok": False}
    try:
        collect_out = collect_site(cfg, data_dir=data_dir)
        touch_site(site_id, checkin=True, data_dir=data_dir)
    except Exception as exc:
        collect_out = {"ok": False, "error": str(exc)}
    validation = validate_edge_readonly(cfg)
    touch_site(
        site_id,
        validation=True,
        traffic=str(validation.get("traffic") or ""),
        error="; ".join(validation.get("errors") or []) if not validation.get("ok") else "",
        data_dir=data_dir,
    )
    return {"collect": collect_out, "validation": validation}
