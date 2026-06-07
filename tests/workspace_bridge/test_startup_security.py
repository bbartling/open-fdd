from __future__ import annotations

import sys
from pathlib import Path

import bcrypt
import pytest

REPO = Path(__file__).resolve().parents[2]

_EXAMPLE_SECRET = "local-dev-secret-min-32-characters-long"
_EXAMPLE_INTEGRATOR_PASS = "msi-local"


def _reload_security(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str | None) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]


def test_reject_example_secret_on_public_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="0.0.0.0",
        OFDD_AUTH_SECRET=_EXAMPLE_SECRET,
        OFDD_INTEGRATOR_USER="integrator",
        OFDD_INTEGRATOR_PASSWORD="unique-password-not-example",
    )
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="example/default auth credentials"):
        validate_startup_auth()


def test_reject_example_password_on_lan_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="192.168.1.10",
        OFDD_AUTH_SECRET="unique-secret-32chars-minimum-ok!!",
        OFDD_INTEGRATOR_USER="integrator",
        OFDD_INTEGRATOR_PASSWORD=_EXAMPLE_INTEGRATOR_PASS,
    )
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="example/default auth credentials"):
        validate_startup_auth()


def test_example_credentials_ok_on_localhost_dev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="127.0.0.1",
        OFDD_AUTH_SECRET=_EXAMPLE_SECRET,
        OFDD_INTEGRATOR_USER="integrator",
        OFDD_INTEGRATOR_PASSWORD=_EXAMPLE_INTEGRATOR_PASS,
    )
    from openfdd_bridge.main import create_app  # noqa: E402

    create_app()


def test_auth_disabled_refused_in_production(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="127.0.0.1",
        OFDD_AUTH_DISABLED="1",
        OFDD_ENV="production",
    )
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="OFDD_ENV=production"):
        validate_startup_auth()


def test_auth_disabled_refused_with_bacnet_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="127.0.0.1",
        OFDD_AUTH_DISABLED="1",
        OFDD_ENABLE_BACNET_WRITE="1",
    )
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="OFDD_ENABLE_BACNET_WRITE"):
        validate_startup_auth()


def test_token_ttl_default_eight_hours(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("OFDD_AUTH_TTL_SEC", raising=False)
    monkeypatch.delenv("OFDD_AUTH_TTL_ALLOW_LONG", raising=False)
    _reload_security(monkeypatch, tmp_path)
    from openfdd_bridge.auth import token_ttl_seconds  # noqa: E402

    assert token_ttl_seconds() == 8 * 3600


def test_token_ttl_clamped_without_allow_long(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog):
    import logging

    caplog.set_level(logging.WARNING)
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_AUTH_TTL_SEC=str(30 * 86400),
    )
    from openfdd_bridge.auth import token_ttl_seconds  # noqa: E402

    assert token_ttl_seconds() == 7 * 86400


def test_password_hash_verification(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    digest = bcrypt.hashpw(b"msi-secret", bcrypt.gensalt()).decode("ascii")
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_AUTH_SECRET="test-secret-key-32chars-minimum!!",
        OFDD_INTEGRATOR_USER="integrator",
        OFDD_INTEGRATOR_PASSWORD="plaintext-should-lose",
        OFDD_INTEGRATOR_PASSWORD_HASH=digest,
    )
    from openfdd_bridge.auth import check_credentials  # noqa: E402

    assert check_credentials("integrator", "msi-secret") == "integrator"
    assert check_credentials("integrator", "plaintext-should-lose") is None


def test_bacnet_write_dry_run_rejects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi import HTTPException

    monkeypatch.setenv("OFDD_BACNET_WRITE_DRY_RUN", "1")
    from openfdd_bridge.bacnet_write_guard import reject_if_dry_run  # noqa: E402

    body = {
        "device_instance": 1001,
        "object_identifier": "analog-value,1",
        "property_identifier": "present-value",
        "value": 72.0,
        "priority": 8,
    }
    with pytest.raises(HTTPException) as exc:
        reject_if_dry_run(request=None, user={"sub": "integrator", "role": "integrator"}, body=body)
    assert exc.value.status_code == 403
    assert "dry-run" in exc.value.detail.lower()


def test_token_ttl_allow_long_ignored_in_production(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_ENV="production",
        OFDD_AUTH_TTL_SEC=str(30 * 86400),
        OFDD_AUTH_TTL_ALLOW_LONG="1",
    )
    from openfdd_bridge.auth import token_ttl_seconds  # noqa: E402

    assert token_ttl_seconds() == 7 * 86400


def test_log_rotation_prunes_archived_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    archive = logs / "audit.20200101T000000Z.jsonl"
    archive.write_text(
        '{"@timestamp":"2020-01-01T00:00:00+00:00","event_type":"old"}\n',
        encoding="utf-8",
    )
    live = logs / "audit.jsonl"
    live.write_text('{"@timestamp":"2099-01-01T00:00:00+00:00","event_type":"new"}\n', encoding="utf-8")
    monkeypatch.setenv("OFDD_AUDIT_LOG_PATH", str(live))
    monkeypatch.setenv("OFDD_LOG_RETENTION_DAYS", "90")
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge.log_rotation") or name == "openfdd_bridge.log_rotation":
            del sys.modules[name]
    from openfdd_bridge.log_rotation import rotate_logs_on_startup  # noqa: E402

    stats = rotate_logs_on_startup()
    assert stats["audit_pruned"] == 1
    assert not archive.exists()


def test_log_rotation_rotates_oversized_local_run_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_dir = tmp_path / "workspace" / ".local-run"
    run_dir.mkdir(parents=True)
    bridge_log = run_dir / "bridge.log"
    bridge_log.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("OFDD_LOCAL_RUN_LOG_MAX_MB", "1")
    monkeypatch.setenv("OFDD_LOG_RETENTION_DAYS", "90")
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge.log_rotation") or name == "openfdd_bridge.log_rotation":
            del sys.modules[name]
    from openfdd_bridge.log_rotation import rotate_logs_on_startup  # noqa: E402

    stats = rotate_logs_on_startup()
    assert stats["local_run_rotated"] == 1
    assert bridge_log.stat().st_size == 0
    archives = list(run_dir.glob("bridge.*.log"))
    assert len(archives) == 1


def test_log_rotation_prunes_old_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    audit = logs / "audit.jsonl"
    audit.write_text(
        '{"@timestamp":"2020-01-01T00:00:00+00:00","event_type":"old"}\n'
        '{"@timestamp":"2099-01-01T00:00:00+00:00","event_type":"new"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OFDD_AUDIT_LOG_PATH", str(audit))
    monkeypatch.setenv("OFDD_LOG_RETENTION_DAYS", "90")
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge.log_rotation") or name == "openfdd_bridge.log_rotation":
            del sys.modules[name]
    from openfdd_bridge.log_rotation import rotate_logs_on_startup  # noqa: E402

    stats = rotate_logs_on_startup()
    assert stats["audit_pruned"] == 1
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "new" in lines[0]
