"""Trigger FDD run now — touch trigger file for loop, or run directly."""

from pathlib import Path

from fastapi import APIRouter

from open_fdd.platform.config import get_platform_settings

router = APIRouter(tags=["run-fdd"])


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
