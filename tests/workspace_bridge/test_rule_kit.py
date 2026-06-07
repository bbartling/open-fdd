"""Rule Lab dev kit — export zip + Arrow-only upload validation."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

ARROW_RULE = """import pyarrow as pa
import pyarrow.compute as pc

VALUE_COLUMN = "SAT"
MAX_TEMP = 50.0

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(pc.cast(table[VALUE_COLUMN], pa.float64()), MAX_TEMP)
"""

LEGACY_RULE = """
def evaluate(row, cfg):
    return row.get("SAT", 0) > cfg.get("high", 50)
"""

BAD_SIGNATURE = """
def apply_faults_arrow(rows, settings):
    return rows
"""


@pytest.fixture
def authed_integrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data_dir))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app

    client = TestClient(create_app())
    login = client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "changeme"},
    )
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    return client


def test_validate_upload_rejects_legacy():
    from openfdd_bridge.rule_kit import RuleKitError, validate_uploaded_rule

    with pytest.raises(RuleKitError, match="legacy"):
        validate_uploaded_rule(LEGACY_RULE)


def test_validate_upload_rejects_bad_entrypoint_signature():
    from openfdd_bridge.rule_kit import RuleKitError, validate_uploaded_rule

    with pytest.raises(RuleKitError, match="apply_faults_arrow must accept"):
        validate_uploaded_rule(BAD_SIGNATURE)


def test_validate_upload_accepts_arrow():
    from openfdd_bridge.rule_kit import validate_uploaded_rule

    out = validate_uploaded_rule(ARROW_RULE)
    assert out["backend"] == "arrow"
    assert out["ok"] is True


def test_augment_rule_injects_value_stats():
    from openfdd_bridge.rule_kit import augment_rule_code_for_kit_export

    src = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["oa-t"], 70)
"""
    out = augment_rule_code_for_kit_export(src)
    assert "_kit_value_stats" in out
    assert "_kit_value_stats(table)" in out


def test_build_rule_kit_zip_contains_expected_files(tmp_path, monkeypatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_kit import build_rule_kit_zip

    payload, name = build_rule_kit_zip(site_id="demo", lookback_hours=24)
    assert name.endswith(".zip")
    zf = zipfile.ZipFile(io.BytesIO(payload))
    names = set(zf.namelist())
    assert {
        "rule.py",
        "data.py",
        "sample.feather",
        "run_test.py",
        "requirements.txt",
        "column_map.json",
        "README.md",
    } <= names
    assert "config.json" not in names
    assert "python run_test.py" in zf.read("README.md").decode()
    rule_py = zf.read("rule.py").decode()
    assert "apply_faults_arrow" in rule_py
    assert "_kit_value_stats" in rule_py
    assert "open-fdd>=3.0.1" in zf.read("requirements.txt").decode()
    run_test = zf.read("run_test.py").decode()
    assert 'apply_faults_arrow(table, {}, context={"site_id": data.SITE_ID})' in run_test


def test_export_kit_route(authed_integrator: TestClient):
    r = authed_integrator.get("/api/rules/export-kit?site_id=demo&lookback_hours=24")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "rule.py" in zf.namelist()


def test_upload_rule_py_route(authed_integrator: TestClient):
    files = {"file": ("zone_flatline.py", ARROW_RULE, "text/x-python")}
    r = authed_integrator.post("/api/rules/upload", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "apply_faults_arrow" in body["rule"]["code"] or body["rule"]["id"]

    listing = authed_integrator.get("/api/rules/saved").json()["rules"]
    assert any(rr["name"] == "Zone Flatline" for rr in listing)

    bad = authed_integrator.post(
        "/api/rules/upload",
        files={"file": ("bad.py", LEGACY_RULE, "text/x-python")},
    )
    assert bad.status_code == 400
