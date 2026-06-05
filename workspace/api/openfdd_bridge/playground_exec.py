"""Run Rule Lab jobs in a separate OS process so hangs cannot block the API worker."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .security import inprocess_playground_allowed


def subprocess_enabled() -> bool:
    if inprocess_playground_allowed():
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
        try:
            df.to_parquet(work_dir / "job.parquet", index=False)
            return
        except Exception:
            pass
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


def _minimal_worker_env(api_root: Path, work_dir: Path) -> dict[str, str]:
    """Pass only safe runtime variables — never auth secrets or arbitrary OFDD_* vars."""
    repo_root = os.environ.get("OPENFDD_REPO_ROOT", "").strip()
    py_path = os.environ.get("PYTHONPATH", "")
    roots = [str(api_root), repo_root] if repo_root else [str(api_root)]
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": os.pathsep.join(p for p in (*roots, py_path) if p),
        "OFDD_PLAYGROUND_SUBPROCESS": "1",
        "TMPDIR": str(work_dir),
    }
    if repo_root:
        env["OPENFDD_REPO_ROOT"] = repo_root
    return env


def _apply_resource_limits() -> None:
    """Best-effort POSIX limits; no-op when unavailable."""
    if not hasattr(os, "setrlimit"):
        return
    try:
        import resource

        mem_mb = _memory_limit_mb()
        limit = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:
        return


def _run_worker(cmd: list[str], *, env: dict[str, str], cwd: Path, timeout_s: float) -> subprocess.CompletedProcess[bytes]:
    grace = max(15.0, timeout_s * 0.5 + 10.0)
    total = timeout_s + grace
    preexec = os.setsid if hasattr(os, "setsid") else None
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(cwd),
        preexec_fn=preexec,
    )
    try:
        stdout, stderr = proc.communicate(timeout=total)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg") and preexec is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=2)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
        else:
            proc.kill()
        proc.communicate()
        raise


def run_pickled_job(job: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    """Spawn ``playground_worker``; return parsed result.json (pickle-free IPC)."""
    job = dict(job)

    with tempfile.TemporaryDirectory(prefix="ofdd-pg-") as tmp:
        td = Path(tmp)
        try:
            _write_job_bundle(td, job, timeout_s=timeout_s)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)[:500]}

        result_path = td / "result.json"
        api_root = Path(__file__).resolve().parent.parent
        env = _minimal_worker_env(api_root, td)
        cmd = [
            sys.executable,
            "-m",
            "openfdd_bridge.playground_worker",
            str(td),
        ]
        try:
            proc = _run_worker(cmd, env=env, cwd=td, timeout_s=timeout_s)
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": "script execution timed out",
                "timed_out": True,
            }

        if not result_path.is_file():
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")[:800]
            stdout = (proc.stdout or b"").decode("utf-8", errors="replace")[:400]
            detail = stderr or stdout or f"exit {proc.returncode}"
            return {
                "ok": False,
                "error": f"playground worker produced no result ({detail})",
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
