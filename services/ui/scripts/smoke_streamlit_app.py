"""Programmatic Streamlit smoke check — catch ImportError / script exceptions early.

Usage (from vibe_code_apps_19):
  py -3.14 scripts/smoke_streamlit_app.py

Env:
  VIBE19_BOOTSTRAP_SKIP_RULES=1  — load bootstrap data/settings but skip 50-rule auto-run (faster)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    # Import chain that previously broke Export tab / main()
    from app.agent_api import make_session_config  # noqa: F401
    from app.bootstrap import read_bootstrap
    from app.rcx_plots import rcx_preset_coverage  # noqa: F401

    assert callable(rcx_preset_coverage)
    assert callable(make_session_config)

    boot = read_bootstrap()
    if boot:
        print(f"Bootstrap present: package={boot.get('package_path')!r} auto_run={boot.get('auto_run_rules')}")
    else:
        print("No bootstrap file (empty-session smoke)")

    # Fast path for CI / smoke when a full B100 auto-run would exceed timeouts
    os.environ.setdefault("VIBE19_BOOTSTRAP_SKIP_RULES", "1")
    # Do not restore a developer leftover upload into AppTest
    os.environ.setdefault("VIBE19_BROWSER_AUTOLOAD", "0")

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=180)
    at.run()
    if at.exception:
        print("FAIL: AppTest exceptions:")
        for exc in at.exception:
            print(f"  - {exc}")
        return 1
    status = ""
    # session_state may expose bootstrap_status after run
    try:
        status = str(at.session_state.get("bootstrap_status") or "")
    except Exception:
        status = ""
    print(f"OK: AppTest 0 exceptions; bootstrap_status={status!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
