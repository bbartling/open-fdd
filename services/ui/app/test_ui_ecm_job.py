"""OFDD-076/072 — ECM package agent-build request + cascade-if-ready honesty (mock streamlit)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("streamlit", MagicMock())

from app import job_store, ui_ecm_job  # noqa: E402


def test_build_ecm_request_honesty_delegated_when_engine_present() -> None:
    req = ui_ecm_job.build_ecm_package_request(
        job_id="job-11111111-1111-1111-1111-111111111111",
        building_id="BUILDING_100",
        run_id="run-22222222-2222-2222-2222-222222222222",
        ecm_available=True,
        wattlab_cli="/usr/bin/wattlab",
    )
    assert req["kind"] == "ecm_package_request"
    assert req["building_id"] == "BUILDING_100"
    assert req["honesty"]["openfdd"] == "delegated"
    assert req["engine"]["open_fdd_ecm_engineering"] is True
    assert req["engine"]["wattlab_agent_build"] == "/usr/bin/wattlab"


def test_build_ecm_request_honesty_unavailable_without_engine() -> None:
    req = ui_ecm_job.build_ecm_package_request(
        job_id="job-1",
        building_id="B50",
        ecm_available=False,
    )
    assert req["honesty"]["openfdd"] == "unavailable"
    assert req["engine"]["open_fdd_ecm_engineering"] is False


def test_cascade_readiness_gate(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("OPENFDD_ENERGYPLUS_MCP", raising=False)
    monkeypatch.delenv("OPENFDD_ENERGYPLUS_MCP_IMAGE", raising=False)
    monkeypatch.setenv("OPENFDD_DOCKER_SOCK", "/nonexistent/docker.sock")
    r = ui_ecm_job.cascade_readiness()
    assert r["ready"] is False
    assert r["reasons"]

    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setenv("OPENFDD_ENERGYPLUS_MCP", "1")
    r2 = ui_ecm_job.cascade_readiness()
    assert r2["ready"] is True
    assert r2["docker_sock"] is True
    assert r2["energyplus_mcp"] is True


def test_maybe_cascade_escoscreen_only_when_not_ready(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("OPENFDD_ENERGYPLUS_MCP", raising=False)
    monkeypatch.delenv("OPENFDD_ENERGYPLUS_MCP_IMAGE", raising=False)
    monkeypatch.setenv("OPENFDD_DOCKER_SOCK", "/nonexistent/docker.sock")
    out = ui_ecm_job.maybe_cascade_eplus("job-1")
    assert out["cascaded"] is False
    assert out["honesty"] == "esco_screening_only"


def test_maybe_cascade_queues_when_ready(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setenv("OPENFDD_ENERGYPLUS_MCP", "1")
    fake = {"ok": True, "run": {"eplus_run_id": "eplus-1", "status": "QUEUED"}}
    with patch.object(
        ui_ecm_job.central_client, "jobs_queue_eplus_run", return_value=fake
    ) as mock_q:
        out = ui_ecm_job.maybe_cascade_eplus("job-1", model_ref="model.idf")
    assert out["cascaded"] is True
    assert out["honesty"] == "delegated_external_runner"
    mock_q.assert_called_once()


def test_create_ecm_request_writes_under_job_wattlab(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "workspace"
    meta = job_store.create_job("ECM Test", building_name="BUILDING_100", ws=ws)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("OPENFDD_ENERGYPLUS_MCP", raising=False)
    monkeypatch.setenv("OPENFDD_DOCKER_SOCK", "/nonexistent/docker.sock")

    result = ui_ecm_job.create_ecm_package_request(
        meta.job_id,
        building_id="BUILDING_100",
        notes="unit test",
        do_cascade=False,
        ws=ws,
    )
    assert result["ok"] is True
    from pathlib import Path

    path = Path(result["path"])
    assert path.is_file()
    assert "wattlab" in path.parts and "ecm" in path.parts
    import json

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["kind"] == "ecm_package_request"
    assert saved["job_id"] == meta.job_id
    assert saved["building_id"] == "BUILDING_100"
    assert "honesty" in saved


def test_discover_wattlab_xlsx_nested(tmp_path, monkeypatch) -> None:
    root = tmp_path / "wattlab_ws"
    nested = root / "reports" / "notebooks" / "pkg_a"
    nested.mkdir(parents=True)
    (nested / "book.xlsx").write_bytes(b"PK")  # minimal placeholder
    (root / "reports" / "notebooks" / "top.xlsx").write_bytes(b"PK")
    monkeypatch.setenv("OPENFDD_WATTLAB_WORKSPACE", str(root))
    monkeypatch.delenv("WATTLAB_WORKSPACE", raising=False)
    monkeypatch.delenv("OPENFDD_WORKSPACE", raising=False)
    hits = ui_ecm_job.discover_wattlab_xlsx()
    assert len(hits) == 2
    assert any(h.endswith("top.xlsx") for h in hits)
    assert any("pkg_a" in h and h.endswith("book.xlsx") for h in hits)
