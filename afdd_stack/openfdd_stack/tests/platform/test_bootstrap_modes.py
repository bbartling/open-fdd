"""Bootstrap script tests — single VOLTTRON-first scripts/bootstrap.sh."""

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BOOTSTRAP = _REPO_ROOT / "afdd_stack" / "scripts" / "bootstrap.sh"


def test_bootstrap_is_self_contained_volttron_entry():
    text = _BOOTSTRAP.read_text(encoding="utf-8")
    assert "VOLTTRON" in text
    assert "OFDD_VOLTTRON_DIR" in text
    assert "bootstrap_volttron.sh" not in text


def test_bootstrap_has_compose_db_optional():
    text = _BOOTSTRAP.read_text(encoding="utf-8")
    assert "--compose-db" in text
    assert "--build-openfdd-ui" in text
    assert "--write-openfdd-ui-agent-config" in text
    assert "--volttron-config-stub" in text
    assert "--print-vcfg-hints" in text


def test_bootstrap_doctor_runs_read_only_checks():
    res = subprocess.run(
        [str(_BOOTSTRAP), "--doctor"],
        cwd=str(_REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = (res.stdout or "") + (res.stderr or "")
    assert res.returncode in (0, 1)
    assert "VOLTTRON bootstrap doctor" in out


def test_bootstrap_help_lists_options():
    res = subprocess.run(
        [str(_BOOTSTRAP), "--help"],
        cwd=str(_REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0
    assert "--clone-volttron" in res.stdout
    assert "--install-venv" in res.stdout
    assert "--doctor" in res.stdout


def test_bootstrap_rejects_unknown_option():
    res = subprocess.run(
        [str(_BOOTSTRAP), "--not-a-real-flag"],
        cwd=str(_REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 1
    out = (res.stdout or "") + (res.stderr or "")
    assert "Unknown option" in out
