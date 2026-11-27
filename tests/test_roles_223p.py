"""The 223P role file and the vendored binding are generated from roles/openfdd-roles.json."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_role_file_is_generated_and_imports_223p():
    run = subprocess.run([sys.executable, str(ROOT / "scripts/nf/gen_roles_223p.py"), "--check"],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    ttl = (ROOT / "sql/fdd/roles-223p.ttl").read_text(encoding="utf-8")
    assert "owl:imports <http://data.ashrae.org/standard223/1.0/model/all>" in ttl
    names = (ROOT / "sql/fdd/input_names_223p.json").read_text(encoding="utf-8")
    assert '"version": "1.1.0-draft.1"' in names
    for app in ("nf-app", "lite"):
        vendor = ROOT / app / "static" / "roles"
        assert (vendor / "openfdd-roles.json").is_file()
        assert (vendor / "role-binding.json").is_file()
        assert (vendor / "roles.sha256").read_text(encoding="utf-8").strip()
