"""Milestone D3 — job-native WattLab handoff payload shape (mock streamlit)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("streamlit", MagicMock())

from app import ui_wattlab_job  # noqa: E402


def test_build_handoff_payload_shape() -> None:
    payload = ui_wattlab_job.build_handoff_payload(
        job_id="job-11111111-1111-1111-1111-111111111111",
        run_id="run-22222222-2222-2222-2222-222222222222",
        findings_revision="findings-rev-1",
        profile="diagnostic",
        notes="d3 test",
    )
    assert payload["schema_version"] == "1"
    assert payload["job_id"].startswith("job-")
    assert payload["run_id"].startswith("run-")
    assert payload["findings_revision"] == "findings-rev-1"
    assert payload["source"] == "job_native"
    assert payload["kind"] == "wattlab_handoff"
    assert payload["profile"] == "diagnostic"
    assert payload["notes"] == "d3 test"


def test_create_job_native_handoff_posts_to_central() -> None:
    fake = {
        "ok": True,
        "handoff": {
            "schema_version": "1",
            "handoff_id": "handoff-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "job_id": "job-11111111-1111-1111-1111-111111111111",
            "source": "job_native",
            "kind": "wattlab_handoff",
            "profile": "summary",
            "created_at": "2026-07-28T00:00:00Z",
        },
    }
    with patch.object(
        ui_wattlab_job.central_client, "jobs_create_wattlab_handoff", return_value=fake
    ) as mock_post:
        out = ui_wattlab_job.create_job_native_handoff(
            "job-11111111-1111-1111-1111-111111111111",
            profile="summary",
        )
    assert out["ok"] is True
    assert out["handoff"]["handoff_id"].startswith("handoff-")
    assert out["handoff"]["source"] == "job_native"
    mock_post.assert_called_once()
    args, _kwargs = mock_post.call_args
    assert args[0].startswith("job-")
    posted = args[1]
    assert posted["kind"] == "wattlab_handoff"
    assert posted["source"] == "job_native"
    assert posted["schema_version"] == "1"
