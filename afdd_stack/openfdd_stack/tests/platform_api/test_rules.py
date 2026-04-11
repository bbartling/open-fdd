"""Tests for rules API (GET /rules, GET /rules/{filename})."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from openfdd_stack.platform.api.main import app
from openfdd_stack.platform.api import rules as rules_module

client = TestClient(app)


def test_rules_list_returns_dir_and_files(tmp_path: Path):
    (tmp_path / "sensor_bounds.yaml").write_text("rule: sensor_bounds\n")
    (tmp_path / "sensor_flatline.yaml").write_text("rule: flatline\n")
    (tmp_path / "README.md").write_text("not yaml")

    with patch(
        "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
    ):
        r = client.get("/rules")
    assert r.status_code == 200
    data = r.json()
    assert data["rules_dir"] == str(tmp_path.resolve())
    assert set(data["files"]) == {"sensor_bounds.yaml", "sensor_flatline.yaml"}
    assert "error" not in data


def test_rules_list_when_not_directory(tmp_path: Path):
    not_dir = tmp_path / "missing"
    # ensure it doesn't exist (or is a file)
    (tmp_path / "missing").write_text("x")

    with patch("openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=not_dir):
        r = client.get("/rules")
    assert r.status_code == 200
    data = r.json()
    assert data["rules_dir"] == str(not_dir.resolve())
    assert data["files"] == []
    assert data.get("error") == "rules_dir is not a directory"


def test_rules_get_file_returns_plain_text(tmp_path: Path):
    (tmp_path / "foo.yaml").write_text("rule: foo\nkey: value\n")

    with patch(
        "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
    ):
        r = client.get("/rules/foo.yaml")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/plain")
    assert r.text == "rule: foo\nkey: value\n"


def test_rules_get_file_only_yaml_allowed(tmp_path: Path):
    with patch(
        "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
    ):
        r = client.get("/rules/foo.txt")
    assert r.status_code == 400
    msg = (r.json().get("error") or {}).get("message") or r.json().get("detail") or ""
    assert "yaml" in msg.lower()


def test_rules_get_file_rejects_path_traversal(tmp_path: Path):
    # Validation rejects ".." and "/" in filename (test handler directly; client may normalize URL)
    with pytest.raises(HTTPException) as exc_info:
        with patch(
            "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
        ):
            rules_module.get_rule_file("../etc/passwd.yaml")
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info2:
        with patch(
            "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
        ):
            rules_module.get_rule_file("subdir/other.yaml")
    assert exc_info2.value.status_code == 400


def test_rules_get_file_not_found(tmp_path: Path):
    with patch(
        "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
    ):
        r = client.get("/rules/nonexistent.yaml")
    assert r.status_code == 404


def test_rules_upload_and_delete(tmp_path: Path):
    """POST /rules uploads a file; DELETE /rules/{filename} removes it."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    with patch(
        "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
    ):
        r = client.post(
            "/rules",
            json={
                "filename": "my_rule.yaml",
                "content": "name: my_rule\nflag: my_rule_flag\n",
            },
        )
        assert r.status_code == 200
        assert (tmp_path / "my_rule.yaml").is_file()
        assert "my_rule" in (tmp_path / "my_rule.yaml").read_text()

        r2 = client.delete("/rules/my_rule.yaml")
        assert r2.status_code == 200
        assert not (tmp_path / "my_rule.yaml").exists()


def test_rules_upload_rejects_invalid_yaml(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    with patch(
        "openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path
    ):
        r = client.post(
            "/rules", json={"filename": "bad.yaml", "content": "not: a: valid: yaml"}
        )
        assert r.status_code == 400
        r2 = client.post(
            "/rules",
            json={"filename": "no_name.yaml", "content": "description: only\n"},
        )
        assert r2.status_code == 400


def test_rules_sync_definitions():
    """POST /rules/sync-definitions returns 200 when sync runs (mock to avoid DB)."""
    with patch(
        "openfdd_stack.platform.loop.sync_fault_definitions_from_rules_dir", lambda: None
    ):
        r = client.post("/rules/sync-definitions")
    assert r.status_code == 200


def test_rules_test_inject_disabled_by_default():
    """POST /rules/test-inject returns 403 when OFDD_ALLOW_TEST_RULES is not set."""
    with patch("openfdd_stack.platform.api.rules._ALLOW_TEST_RULES", False):
        r = client.post(
            "/rules/test-inject", json={"filename": "test.yaml", "content": "name: x\n"}
        )
    assert r.status_code == 403


def test_rules_test_inject_and_delete_when_allowed(tmp_path: Path):
    """When OFDD_ALLOW_TEST_RULES=1, POST test-inject creates file and DELETE removes it."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    with (
        patch("openfdd_stack.platform.api.rules._ALLOW_TEST_RULES", True),
        patch("openfdd_stack.platform.api.rules._rules_dir_resolved", return_value=tmp_path),
    ):
        r = client.post(
            "/rules/test-inject",
            json={
                "filename": "hot_reload_test.yaml",
                "content": "name: hot_reload_test\nflag: hot_reload_test\n",
            },
        )
        assert r.status_code in (200, 201)
        assert (tmp_path / "hot_reload_test.yaml").is_file()
        assert (
            tmp_path / "hot_reload_test.yaml"
        ).read_text().strip() == "name: hot_reload_test\nflag: hot_reload_test"

        r2 = client.delete("/rules/test-inject/hot_reload_test.yaml")
        assert r2.status_code in (200, 204)
        assert not (tmp_path / "hot_reload_test.yaml").exists()
