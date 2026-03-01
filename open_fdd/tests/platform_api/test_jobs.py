"""Jobs API tests: POST /jobs/fdd/run, GET /jobs/{id}."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def test_job_create_fdd_run():
    with patch("open_fdd.platform.jobs.run_fdd_job"):  # avoid running real FDD in test
        r = client.post("/jobs/fdd/run", json={})
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data.get("status") == "queued"
    job_id = data["job_id"]
    r2 = client.get(f"/jobs/{job_id}")
    assert r2.status_code == 200
    assert r2.json()["job_type"] == "fdd.run"
    assert r2.json()["status"] in ("queued", "running", "finished")
