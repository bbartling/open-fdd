"""The agent spec must name paths, commands and rule ids that exist in this tree."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_spec_check", ROOT / "scripts/check_agent_spec.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_live_spec_matches_the_tree():
    assert mod.check(ROOT) == []


def test_unknown_rule_id_is_rejected():
    assert mod.rule_id_errors("`SV-STALE`", {"SV-STALE"}) == []
    assert any("SV-NOPE" in error for error in mod.rule_id_errors("`SV-NOPE`", {"SV-STALE"}))


def test_missing_path_is_rejected():
    assert mod.path_errors("`scripts/check_agent_spec.py`", ROOT) == []
    assert any("missing" in error for error in mod.path_errors("`scripts/not-a-real-file.py`", ROOT))
