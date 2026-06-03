"""Child process entry for isolated Rule Lab execution (pickled job in / result out)."""

from __future__ import annotations

import os
import pickle
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
    except (ImportError, OSError, ValueError):
        pass


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
        import pandas as pd

        from .playground import _run_dataframe_script_impl

        df = pickle.loads(job["df_bytes"])
        if not isinstance(df, pd.DataFrame):
            raise TypeError("run_script job missing DataFrame")
        return {"ok": True, "result": _run_dataframe_script_impl(job["code"], df, cfg=job.get("cfg") or {})}
    raise ValueError(f"unknown playground job op: {op!r}")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: python -m openfdd_bridge.playground_worker <job.pkl> <result.pkl>", file=sys.stderr)
        return 2
    job_path = Path(args[0])
    result_path = Path(args[1])
    try:
        job = pickle.loads(job_path.read_bytes())
        cpu_s = float(job.get("timeout_s") or 30.0)
        mem_mb = int(job.get("memory_mb") or 512)
        _apply_resource_limits(cpu_s, mem_mb)
        payload = execute_job(job)
        result_path.write_bytes(pickle.dumps(payload))
        return 0
    except Exception as exc:
        err = {
            "ok": False,
            "error": str(exc)[:500],
            "error_type": exc.__class__.__name__,
        }
        result_path.write_bytes(pickle.dumps(err))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
