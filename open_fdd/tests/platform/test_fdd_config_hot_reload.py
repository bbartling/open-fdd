"""Tests that FDD rule runner uses platform config and loads rules from disk every run (hot reload).

Protects: OpenFDD config (rules_dir, rule_interval_hours, lookback_days), GET /config and
GET /rules parity with the loop, and that run_fdd_loop does not cache rules (analyst can
tune YAML and see changes on next run).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from open_fdd.platform.config import set_config_overlay


@pytest.fixture(autouse=True)
def _clear_overlay():
    yield
    set_config_overlay({})


def _mock_conn_no_sites():
    """Context manager yielding a mock DB connection with no sites (so run_fdd_loop does not run rules)."""
    cur = MagicMock()
    cur.execute = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def test_run_fdd_loop_loads_rules_from_disk_every_run(tmp_path):
    """run_fdd_loop calls load_rules_from_dir on every run (no cache); path comes from platform config."""
    (tmp_path / "one.yaml").write_text("name: one\ntype: bounds\n")
    set_config_overlay({"rules_dir": str(tmp_path.resolve())})

    load_calls = []

    def record_load(path):
        load_calls.append(Path(path).resolve())
        return []  # no rules so runner gets empty list

    with patch("open_fdd.platform.loop.get_conn", return_value=_mock_conn_no_sites()):
        with patch("open_fdd.engine.runner.load_rules_from_dir", side_effect=record_load):
            from open_fdd.platform.loop import run_fdd_loop

            run_fdd_loop()
            run_fdd_loop()
    assert len(load_calls) == 2, "load_rules_from_dir must be called every run (hot reload)"
    assert load_calls[0] == load_calls[1] == tmp_path.resolve()
    assert load_calls[0].name == tmp_path.name


def test_run_fdd_loop_uses_rules_dir_from_settings(tmp_path):
    """run_fdd_loop uses rules_dir from get_platform_settings() when not overridden."""
    (tmp_path / "x.yaml").write_text("name: x\n")
    set_config_overlay({"rules_dir": str(tmp_path.resolve())})

    with patch("open_fdd.platform.loop.get_conn", return_value=_mock_conn_no_sites()):
        with patch("open_fdd.engine.runner.load_rules_from_dir") as m:
            m.return_value = []
            from open_fdd.platform.loop import run_fdd_loop

            run_fdd_loop()
    m.assert_called_once()
    (call_path,) = m.call_args[0]
    assert Path(call_path).resolve() == tmp_path.resolve()


def test_rules_api_and_loop_resolve_same_path_for_relative_rules_dir():
    """API _rules_dir_resolved() and run_fdd_loop use the same repo-relative path for rules_dir."""
    set_config_overlay({"rules_dir": "analyst/rules"})

    from open_fdd.platform import loop as loop_mod
    from open_fdd.platform.api import rules as rules_mod

    # Loop: repo_root from loop.py (open_fdd/platform/loop.py -> parent.parent.parent)
    loop_repo_root = Path(loop_mod.__file__).resolve().parent.parent.parent
    expected = (loop_repo_root / "analyst" / "rules").resolve()

    api_resolved = rules_mod._rules_dir_resolved()
    assert api_resolved == expected, (
        "GET /rules and FDD loop must resolve the same rules dir (API uses same repo_root logic)"
    )
