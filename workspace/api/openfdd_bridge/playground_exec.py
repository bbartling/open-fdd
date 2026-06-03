"""Run Rule Lab jobs in a separate OS process so hangs cannot block the API worker."""

from __future__ import annotations

import json
import os
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


def _max_job_rows() -> int:
    try:
        return max(1000, int(os.environ.get("OFDD_PLAYGROUND_MAX_ROWS", "50000")))
    except ValueError:
        return 50000


def _parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        return False


def _write_df_ipc(work_dir: Path, df: Any) -> None:
    """Persist DataFrame without pickle (parquet preferred, JSON fallback)."""
    import pandas as pd

    if not isinstance(df, pd.DataFrame):
        raise TypeError("run_script job missing DataFrame")
    if _parquet_available():
        df.to_parquet(work_dir / "job.parquet", index=False)
        return
    df.to_json(work_dir / "job.df.json", orient="split", date_format="iso")


def _read_df_ipc(work_dir: Path) -> Any:
    import pandas as pd

    parquet = work_dir / "job.parquet"
    if parquet.is_file():
        return pd.read_parquet(parquet)
    json_path = work_dir / "job.df.json"
    if not json_path.is_file():
        raise FileNotFoundError("job.parquet or job.df.json required for run_script")
    return pd.read_json(json_path, orient="split")


def _write_job_bundle(work_dir: Path, job: dict[str, Any], *, timeout_s: float) -> None:
    """Write JSON metadata + optional parquet DataFrame (no pickle)."""
    import pandas as pd

    op = job.get("op")
    body: dict[str, Any] = {
        "op": op,
        "code": job.get("code"),
        "cfg": job.get("cfg") or {},
        "capture_print": bool(job.get("capture_print", True)),
    }
    if op == "sweep_rule":
        rows = job.get("rows") or []
        if len(rows) > _max_job_rows():
            raise ValueError(f"row count {len(rows)} exceeds OFDD_PLAYGROUND_MAX_ROWS ({_max_job_rows()})")
        body["rows"] = rows
    elif op == "run_script":
        df = job.get("df")
        if not isinstance(df, pd.DataFrame):
            raise TypeError("run_script job missing DataFrame")
        _write_df_ipc(work_dir, df)
    else:
        raise ValueError(f"unknown playground job op: {op!r}")

    meta = {"timeout_s": float(timeout_s), "memory_mb": _memory_limit_mb()}
    (work_dir / "job.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (work_dir / "job.json").write_text(json.dumps(body), encoding="utf-8")


def _read_result_json(result_path: Path) -> dict[str, Any]:
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("playground result must be a JSON object")
    if "ok" not in raw:
        raise ValueError("playground result missing ok field")
    return raw


def run_pickled_job(job: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    """Spawn ``playground_worker``; return parsed result.json (pickle-free IPC)."""
    job = dict(job)
    if job.get("op") == "run_script" and "df_bytes" in job:
        import pickle

        job["df"] = pickle.loads(job.pop("df_bytes"))

    with tempfile.TemporaryDirectory(prefix="ofdd-pg-") as tmp:
        td = Path(tmp)
        try:
            _write_job_bundle(td, job, timeout_s=timeout_s)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)[:500]}

        result_path = td / "result.json"
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
            str(td),
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

        try:
            payload = _read_result_json(result_path)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            return {
                "ok": False,
                "error": f"invalid playground result: {exc}",
                "worker_exit": proc.returncode,
            }

        if proc.returncode != 0 and payload.get("ok") is not False:
            payload = {
                "ok": False,
                "error": payload.get("error") or f"playground worker exited {proc.returncode}",
            }
        return payload
