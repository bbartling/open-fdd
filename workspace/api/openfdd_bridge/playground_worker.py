"""Child process entry for isolated Rule Lab execution (JSON + parquet IPC)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _apply_resource_limits(cpu_seconds: float, memory_mb: int) -> None:
    try:
        import resource

        cpu = max(5, int(cpu_seconds) + 5)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        if memory_mb > 0:
            cap = memory_mb * 1024 * 1024
            for attr in ("RLIMIT_AS", "RLIMIT_RSS", "RLIMIT_DATA"):
                if hasattr(resource, attr):
                    resource.setrlimit(getattr(resource, attr), (cap, cap))
                    break
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"playground resource limits failed (cpu_seconds={cpu_seconds}, memory_mb={memory_mb})"
        ) from exc


def _load_job(work_dir: Path) -> dict[str, Any]:
    meta_path = work_dir / "job.meta.json"
    job_path = work_dir / "job.json"
    if not meta_path.is_file() or not job_path.is_file():
        raise FileNotFoundError("job.meta.json and job.json required")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    body = json.loads(job_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or not isinstance(body, dict):
        raise ValueError("job bundle must be JSON objects")
    merged = {**body, **meta}
    op = merged.get("op")
    if op == "run_script":
        from .playground_exec import _read_df_ipc

        merged["df"] = _read_df_ipc(work_dir)
    return merged


def _write_result(result_path: Path, payload: dict[str, Any]) -> None:
    result_path.write_text(json.dumps(payload, default=str), encoding="utf-8")


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    """Run a playground job in-process (called only from the worker subprocess)."""
    os.environ["OFDD_PLAYGROUND_INPROCESS"] = "1"
    op = job.get("op")
    if op == "sweep_rule":
        from .playground import _sweep_rule_impl

        flags, events = _sweep_rule_impl(
            job["code"],
            job.get("cfg") or {},
            job.get("rows") or [],
            capture_print=bool(job.get("capture_print", True)),
        )
        return {"ok": True, "flags": flags, "events": events}
    if op == "run_script":
        from .playground import _run_dataframe_script_impl

        df = job["df"]
        return {"ok": True, "result": _run_dataframe_script_impl(job["code"], df, cfg=job.get("cfg") or {})}
    raise ValueError(f"unknown playground job op: {op!r}")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m openfdd_bridge.playground_worker <work_dir>", file=sys.stderr)
        return 2
    work_dir = Path(args[0])
    result_path = work_dir / "result.json"
    try:
        meta = json.loads((work_dir / "job.meta.json").read_text(encoding="utf-8"))
        cpu_s = float(meta.get("timeout_s") or 30.0)
        mem_mb = int(meta.get("memory_mb") or 512)
        _apply_resource_limits(cpu_s, mem_mb)
        job = _load_job(work_dir)
        payload = execute_job(job)
        _write_result(result_path, payload)
        return 0
    except Exception as exc:
        err = {
            "ok": False,
            "error": str(exc)[:500],
            "error_type": exc.__class__.__name__,
        }
        _write_result(result_path, err)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
