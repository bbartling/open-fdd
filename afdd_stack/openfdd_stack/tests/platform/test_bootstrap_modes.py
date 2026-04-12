"""Bootstrap script tests — entry point ./scripts/bootstrap.sh (implementation in afdd_stack/scripts)."""

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BOOTSTRAP = _REPO_ROOT / "scripts" / "bootstrap.sh"
_BOOTSTRAP_IMPL = _REPO_ROOT / "afdd_stack" / "scripts" / "bootstrap.sh"


def test_bootstrap_is_self_contained_volttron_entry():
    text = _BOOTSTRAP_IMPL.read_text(encoding="utf-8")
    assert "VOLTTRON" in text
    assert "OFDD_VOLTTRON_DOCKER_DIR" in text
    assert "OFDD_VOLTTRON_DIR" not in text
    assert "bootstrap_volttron.sh" not in text


def test_bootstrap_has_compose_db_optional():
    text = _BOOTSTRAP_IMPL.read_text(encoding="utf-8")
    assert "--test" in text
    assert "OFDD_BOOTSTRAP_INSTALL_DEV" in text
    assert "run_bootstrap_test" in text
    assert "--volttron-docker" in text
    assert "--clone-volttron-docker" in text
    assert "OFDD_VOLTTRON_DOCKER_DIR" in text
    assert "--compose-db" in text
    assert "--build-openfdd-ui" in text
    assert "--write-openfdd-ui-agent-config" in text
    assert "--volttron-config-stub" in text
    assert "--print-vcfg-hints" in text
    assert "--central-lab" in text
    assert "--verify-fdd-schema" in text
    assert "--write-env-defaults" in text
    assert "America/Chicago" in text or "OFDD_DEFAULT_TZ" in text
    assert "volttron-docker" in text


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
    assert "bootstrap doctor" in out


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
    out = res.stdout
    assert "--volttron-docker" in out
    assert "--clone-volttron-docker" in out
    assert "--install-venv" not in out
    assert "--doctor" in out
    assert "--central-lab" in out
    assert "--verify-fdd-schema" in out
    assert "--test" in out


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
