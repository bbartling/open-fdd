#!/usr/bin/env python3
"""Regenerate CI ip goldens and require byte-for-byte match with committed files (#1284 W0c)."""

from __future__ import annotations

import filecmp
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDENS = ROOT / "tests" / "fixtures" / "si_cutover" / "ip_goldens"


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.stress.si_cutover.ci_fixtures_lib import emit_all_goldens

    with tempfile.TemporaryDirectory(prefix="ip-goldens-regen-") as tmp:
        tmp_dir = Path(tmp)
        emit_all_goldens(tmp_dir)
        committed = sorted(GOLDENS.glob("*.json"))
        generated = sorted(tmp_dir.glob("*.json"))
        if [p.name for p in committed] != [p.name for p in generated]:
            print(
                "FAIL ip_goldens: file set mismatch\n"
                f"  committed: {[p.name for p in committed]}\n"
                f"  generated: {[p.name for p in generated]}",
                file=sys.stderr,
            )
            return 1
        for path in committed:
            if not filecmp.cmp(path, tmp_dir / path.name, shallow=False):
                print(f"FAIL ip_goldens: {path.name} differs from CI regeneration", file=sys.stderr)
                return 1
    print(f"PASS ip_goldens frozen ({len(committed)} files byte-identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
