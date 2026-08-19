#!/usr/bin/env python3
"""Deprecated alias — use ``eplus_parity_compare.py``.

Vibe19 dual-parity is retired; this module remains for cookbook compare helpers
used in tests (``compare_fdd``, ``compare_analytics_tables``).
"""

from eplus_parity_compare import *  # noqa: F403

if __name__ == "__main__":
    from eplus_parity_compare import main

    raise SystemExit(main())
