"""Run Rule Lab jobs in a separate OS process so hangs cannot block the API worker."""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def subprocess_enabled() -> bool:
    if os.environ.get("OFDD_PLAYGROUND_INPROCESS", "").strip() in {"1", "true", "yes"}:
        return False
    if os.environ.get("OFDD_PLAYGROUND_SUBPROCESS", "").strip() in {"0", "false", "no"}:
        return False
    return True


def _memory_limit_mb() -> int:
    try:
        return max(128, int(os.environ.get("OFDD_PLAYGROUND_MEMORY_MB", "512")))
    except ValueError:
        return 512


def run_pickled_job(job: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    """Spawn ``playground_worker``; return unpickled result dict."""
    job = dict(job)
    job["timeout_s"] = timeout_s
    job["memory_mb"] = _memory_limit_mb()

    with tempfile.TemporaryDirectory(prefix="ofdd-pg-") as tmp:
        td = Path(tmp)
        job_path = td / "job.pkl"
        result_path = td / "result.pkl"
        job_path.write_bytes(pickle.dumps(job, protocol=pickle.HIGHEST_PROTOCOL))

        api_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env["OFDD_PLAYGROUND_SUBPROCESS"] = "1"
        env.pop("OFDD_PLAYGROUND_INPROCESS", None)
        py_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(api_root), py_path) if p)
        cmd = [
            sys.executable,
            "-m",
            "openfdd_bridge.playground_worker",
            str(job_path),
            str(result_path),
        ]
        grace = min(10.0, max(2.0, timeout_s * 0.25))
        try:
            proc = subprocess.run(
                cmd,
                timeout=timeout_s + grace,
                capture_output=True,
                env=env,
                cwd=str(api_root),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": "script execution timed out",
                "timed_out": True,
            }

        if not result_path.is_file():
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")[:500]
            return {
                "ok": False,
                "error": "playground worker produced no result",
                "worker_exit": proc.returncode,
                "worker_stderr": stderr,
            }

        payload = pickle.loads(result_path.read_bytes())
        if proc.returncode != 0 and payload.get("ok") is not False:
            payload = {
                "ok": False,
                "error": payload.get("error") or f"playground worker exited {proc.returncode}",
            }
        return payload
