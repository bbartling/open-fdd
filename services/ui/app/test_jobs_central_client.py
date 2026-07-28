"""Milestone C0 — central_client / ui_jobs failure modes."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# ui_jobs imports streamlit at module load; CI installs pytest without streamlit.
sys.modules.setdefault("streamlit", MagicMock())

from app import central_client, ui_jobs  # noqa: E402


def test_jobs_list_central_down() -> None:
    with patch.object(
        central_client, "_request", side_effect=central_client.requests.RequestException("down")
    ):
        out = central_client.jobs_list()
    assert out.get("central_down") is True
    assert out.get("ok") is False


def test_jobs_create_central_down() -> None:
    with patch.object(
        central_client, "_request", side_effect=central_client.requests.RequestException("down")
    ):
        out = central_client.jobs_create("x")
    assert out.get("central_down") is True


def test_list_active_jobs_falls_back_to_filesystem(tmp_path, monkeypatch) -> None:
    from app import job_store

    ws = tmp_path / "workspace"
    ws.mkdir()
    meta = job_store.create_job("Local Only", ws=ws)

    monkeypatch.setattr(ui_jobs, "_ws", lambda: ws)
    with patch.object(central_client, "health_ok", return_value=False):
        jobs, err = ui_jobs._list_active_jobs()
    assert err is None
    assert len(jobs) == 1
    assert jobs[0].job_id == meta.job_id


def test_list_active_jobs_prefers_central() -> None:
    fake = {
        "ok": True,
        "jobs": [
            {
                "schema_version": 1,
                "job_id": "job-11111111-1111-1111-1111-111111111111",
                "job_name": "From API",
                "status": "active",
                "archived": False,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "meta_revision": "abc",
                "tags": [],
                "revisions": {},
            }
        ],
    }
    with patch.object(central_client, "health_ok", return_value=True):
        with patch.object(central_client, "jobs_list", return_value=fake):
            jobs, err = ui_jobs._list_active_jobs()
    assert err is None
    assert jobs[0].job_name == "From API"


def test_list_active_jobs_surfaces_non_down_error() -> None:
    with patch.object(central_client, "health_ok", return_value=True):
        with patch.object(
            central_client,
            "jobs_list",
            return_value={"ok": False, "error": "permission denied"},
        ):
            jobs, err = ui_jobs._list_active_jobs()
    assert jobs == []
    assert err == "permission denied"
