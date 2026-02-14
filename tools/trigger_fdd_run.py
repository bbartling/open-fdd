#!/usr/bin/env python3
"""
Touch the FDD trigger file so the running loop (--loop) runs immediately and resets its timer.

Usage:
  python tools/trigger_fdd_run.py
  python tools/trigger_fdd_run.py --path config/.run_fdd_now

When the fdd-loop container is running with --loop, it checks for this file every 60 seconds.
Create it from host: touch config/.run_fdd_now
Or with Docker: docker compose -f platform/docker-compose.yml exec fdd-loop python tools/trigger_fdd_run.py
"""

import argparse
import sys
from pathlib import Path

# Allow running from tools/ or repo root
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trigger FDD rule run now (when loop is running)"
    )
    parser.add_argument(
        "-p",
        "--path",
        default=None,
        help="Trigger file path (default: from OFDD_FDD_TRIGGER_FILE or config/.run_fdd_now)",
    )
    args = parser.parse_args()

    if args.path:
        path = Path(args.path)
    else:
        try:
            from open_fdd.platform.config import get_platform_settings

            settings = get_platform_settings()
            path_str = getattr(settings, "fdd_trigger_file", None) or "config/.run_fdd_now"
            path = Path(path_str)
        except Exception:
            path = Path("config/.run_fdd_now")

    if not path.is_absolute():
        path = Path.cwd() / path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    print(f"Triggered: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
