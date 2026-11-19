"""The docs gate must detect stale discovery pointers and README metadata."""
import importlib.util
from pathlib import Path
import shutil
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("skills_sync", ROOT / "scripts/check_skills_sync.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


@pytest.fixture
def checkout(tmp_path):
    for directory in ("openfdd_agent_spec/skills", ".agents/skills", ".claude/skills"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    for relative in ("README.md", "VERSION", "nf-app/package.json", "nf-app/static/fdd-catalog.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    return tmp_path


@pytest.mark.parametrize("kind,expected", [
    ("missing", "stale/missing pointer"),
    ("stale", "stale/missing pointer"),
    ("orphan", "pointer without canonical skill"),
    ("badge", "cookbook counts drifted"),
    ("version", "version differs"),
])
def test_drift_is_rejected(checkout, kind, expected):
    assert sync.check(checkout) == []
    pointer = checkout / ".agents/skills/install-upgrade-troubleshoot/SKILL.md"
    if kind == "missing":
        pointer.unlink()
    elif kind == "stale":
        pointer.write_text("stale", encoding="utf-8")
    elif kind == "orphan":
        path = checkout / ".agents/skills/nonexistent/SKILL.md"
        path.parent.mkdir()
        path.write_text("orphan", encoding="utf-8")
    elif kind == "badge":
        path = checkout / "README.md"
        path.write_text(re.sub(r"Cookbook-\d+%20SQL", "Cookbook-0%20SQL", path.read_text(encoding="utf-8")), encoding="utf-8")
    else:
        (checkout / "VERSION").write_text("0.0.0", encoding="utf-8")
    assert any(expected in error for error in sync.check(checkout))
    if kind in ("missing", "stale", "badge"):
        assert sync.check(checkout, write=True) == []
        assert sync.check(checkout) == []
