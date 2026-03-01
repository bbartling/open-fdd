# Config/server validation tests mirroring NR HA migrations/config-server

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app
from open_fdd.platform.api.schemas import (
    CapabilityResponse,
    ErrorResponse,
    FaultStateItem,
    JobResponse,
)

client = TestClient(app)


def test_capabilities_response_schema():
    r = client.get("/capabilities")
    assert r.status_code == 200
    data = r.json()
    parsed = CapabilityResponse.model_validate(data)
    assert parsed.version
    assert isinstance(parsed.features, dict)
    assert "websocket" in parsed.features
    assert "fault_state" in parsed.features
    assert "jobs" in parsed.features
    assert "bacnet_write" in parsed.features


def test_error_response_schema_401():
    with patch("open_fdd.platform.api.auth.get_platform_settings") as m:
        m.return_value.api_key = "x"
        r = client.get("/capabilities")
    assert r.status_code == 401
    data = r.json()
    parsed = ErrorResponse.model_validate(data)
    assert parsed.error.code == "UNAUTHORIZED"
    assert parsed.error.message


def test_error_response_schema_404():
    with patch("open_fdd.platform.api.points.get_conn") as mock_conn:
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=None)
        mock_conn.return_value = conn
        r = client.get("/points/00000000-0000-0000-0000-000000000000")
    data = r.json()
    parsed = ErrorResponse.model_validate(data)
    assert parsed.error.code == "NOT_FOUND"


def test_fault_state_item_schema():
    from datetime import datetime, timezone
    item = FaultStateItem(
        id="id1",
        site_id="default",
        equipment_id="ahu1",
        fault_id="high_discharge_temp",
        active=True,
        last_changed_ts=datetime.now(timezone.utc),
    )
    assert item.active is True
    assert item.fault_id == "high_discharge_temp"


def test_job_response_schema():
    job = JobResponse(
        job_id="j1",
        job_type="fdd.run",
        status="queued",
        created_at="2024-01-01T00:00:00Z",
    )
    assert job.job_type == "fdd.run"
    assert job.status == "queued"
