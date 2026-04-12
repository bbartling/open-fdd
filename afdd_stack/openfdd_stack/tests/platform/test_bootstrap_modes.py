"""Bootstrap script tests — entry point ./scripts/bootstrap.sh (implementation in afdd_stack/scripts)."""

import os
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


def _duplicate_ssl_quarantine_function_source() -> str:
    """Lines 407–432 of afdd_stack/scripts/bootstrap.sh (run_volttron_quarantine_duplicate_ssl_config)."""
    lines = _BOOTSTRAP_IMPL.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[406:432]) + "\n"


def test_volttron_duplicate_ssl_quarantine_moves_config(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(
        "[volttron]\n"
        "web-ssl-cert = /a.pem\n"
        "web-ssl-cert = /b.pem\n"
        "web-ssl-key = /k.key\n",
        encoding="utf-8",
    )
    script = _duplicate_ssl_quarantine_function_source()
    script += f'run_volttron_quarantine_duplicate_ssl_config "{cfg}"\n'
    res = subprocess.run(
        ["bash", "-c", script],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        env={k: v for k, v in os.environ.items() if k != "OFDD_VOLTTRON_CONFIG_STRICT"},
    )
    assert res.returncode == 0, res.stderr
    assert not cfg.is_file()
    backs = list(tmp_path.glob("config.bak.duplicate-ssl.*"))
    assert len(backs) == 1
    assert "Quarantining" in (res.stdout or "")


def test_volttron_duplicate_ssl_quarantine_respects_strict(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(
        "[volttron]\nweb-ssl-cert = /a.pem\nweb-ssl-cert = /b.pem\n",
        encoding="utf-8",
    )
    script = "export OFDD_VOLTTRON_CONFIG_STRICT=1\n"
    script += _duplicate_ssl_quarantine_function_source()
    script += f'run_volttron_quarantine_duplicate_ssl_config "{cfg}"\n'
    res = subprocess.run(
        ["bash", "-c", script],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    assert cfg.is_file()


def test_volttron_ssl_counts_ignore_non_volttron_section(tmp_path):
    """Duplicates under another [section] must not trip quarantine."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "[volttron]\n"
        "web-ssl-cert = /only.pem\n"
        "web-ssl-key = /only.key\n"
        "\n"
        "[other]\n"
        "web-ssl-cert = /x.pem\n"
        "web-ssl-cert = /y.pem\n",
        encoding="utf-8",
    )
    script = _duplicate_ssl_quarantine_function_source()
    script += f'run_volttron_quarantine_duplicate_ssl_config "{cfg}"\n'
    res = subprocess.run(
        ["bash", "-c", script],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        env={k: v for k, v in os.environ.items() if k != "OFDD_VOLTTRON_CONFIG_STRICT"},
    )
    assert res.returncode == 0, res.stderr
    assert cfg.is_file()
    assert "Quarantining" not in (res.stdout or "")
