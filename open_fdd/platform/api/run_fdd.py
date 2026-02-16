"""Trigger FDD run now — touch trigger file for loop, or run directly."""

from pathlib import Path

from fastapi import APIRouter

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn

router = APIRouter(tags=["run-fdd"])


@router.get("/run-fdd/status", summary="Last FDD run (for config UI)")
def run_fdd_status():
    """Return last FDD run from fdd_run_log for UI 'Last run' display."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_ts, status, sites_processed, faults_written FROM fdd_run_log ORDER BY run_ts DESC LIMIT 1"
                )
                row = cur.fetchone()
        if not row:
            return {"last_run": None}
        return {
            "last_run": {
                "run_ts": (
                    row["run_ts"].isoformat()
                    if hasattr(row["run_ts"], "isoformat")
                    else str(row["run_ts"])
                ),
                "status": row["status"],
                "sites_processed": row["sites_processed"],
                "faults_written": row["faults_written"],
            }
        }
    except Exception:
        return {"last_run": None}


@router.post("/run-fdd", summary="Run FDD rules now")
def trigger_run_fdd():
    """
    Trigger an immediate FDD rule run and reset the loop timer.

    **When fdd-loop runs with --loop:** Touches the trigger file; the loop picks it up
    within 60 seconds, runs immediately, and resets its interval.

    **Standalone / no loop:** Run `python tools/run_rule_loop.py` for a one-shot.
    """
    settings = get_platform_settings()
    trigger_path = getattr(settings, "fdd_trigger_file", None) or "config/.run_fdd_now"
    p = Path(trigger_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return {"status": "triggered", "path": str(p)}
