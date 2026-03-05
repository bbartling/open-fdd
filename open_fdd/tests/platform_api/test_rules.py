"""Tests for rules API (GET /rules, GET /rules/{filename})."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app
from open_fdd.platform.api import rules as rules_module

client = TestClient(app)


def test_rules_list_returns_dir_and_files(tmp_path: Path):
    (tmp_path / "sensor_bounds.yaml").write_text("rule: sensor_bounds\n")
    (tmp_path / "sensor_flatline.yaml").write_text("rule: flatline\n")
    (tmp_path / "README.md").write_text("not yaml")

    with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=tmp_path):
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

    with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=not_dir):
        r = client.get("/rules")
    assert r.status_code == 200
    data = r.json()
    assert data["rules_dir"] == str(not_dir.resolve())
    assert data["files"] == []
    assert data.get("error") == "rules_dir is not a directory"


def test_rules_get_file_returns_plain_text(tmp_path: Path):
    (tmp_path / "foo.yaml").write_text("rule: foo\nkey: value\n")

    with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=tmp_path):
        r = client.get("/rules/foo.yaml")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/plain")
    assert r.text == "rule: foo\nkey: value\n"


def test_rules_get_file_only_yaml_allowed(tmp_path: Path):
    with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=tmp_path):
        r = client.get("/rules/foo.txt")
    assert r.status_code == 400
    msg = (r.json().get("error") or {}).get("message") or r.json().get("detail") or ""
    assert "yaml" in msg.lower()


def test_rules_get_file_rejects_path_traversal(tmp_path: Path):
    # Validation rejects ".." and "/" in filename (test handler directly; client may normalize URL)
    with pytest.raises(HTTPException) as exc_info:
        with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=tmp_path):
            rules_module.get_rule_file("../etc/passwd.yaml")
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info2:
        with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=tmp_path):
            rules_module.get_rule_file("subdir/other.yaml")
    assert exc_info2.value.status_code == 400


def test_rules_get_file_not_found(tmp_path: Path):
    with patch("open_fdd.platform.api.rules._rules_dir_resolved", return_value=tmp_path):
        r = client.get("/rules/nonexistent.yaml")
    assert r.status_code == 404
