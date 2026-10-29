#!/usr/bin/env python3
"""Verify ip golden emit succeeds and committed fixtures are well-formed (#1284 W0c).

Regeneration is environment-sensitive (Timescale + pandas oracle). CI proves
``emit_all_goldens`` runs clean on the service DB; committed JSON is schema-checked.
Developers refresh ``tests/fixtures/si_cutover/ip_goldens/`` locally after harness
changes and rely on the si-parity gate for parity semantics.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDENS = ROOT / "tests" / "fixtures" / "si_cutover" / "ip_goldens"
SCHEMA = "si-cutover-ip-golden-v1"


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        print("FAIL ip_goldens: OPENFDD_DATABASE_URL required for regeneration check", file=sys.stderr)
        return 1
    from scripts.stress.si_cutover.ci_fixtures_lib import emit_all_goldens

    with tempfile.TemporaryDirectory(prefix="ip-goldens-regen-") as tmp:
        tmp_dir = Path(tmp)
        emit_all_goldens(tmp_dir, database_url=url)
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
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("schema") != SCHEMA:
            print(f"FAIL ip_goldens: {path.name} bad schema", file=sys.stderr)
            return 1
        if not body.get("building_id"):
            print(f"FAIL ip_goldens: {path.name} missing building_id", file=sys.stderr)
            return 1
    print(
        f"PASS ip_goldens emit ({len(generated)} datasets) + "
        f"{len(committed)} committed schema OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
