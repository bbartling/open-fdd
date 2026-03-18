"""Tests for POST /ai/agent Overview AI endpoint."""

import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def _make_openai_response(content: str) -> MagicMock:
  """Build a minimal mock matching openai.ChatCompletion response shape."""
  choice = MagicMock()
  choice.message.content = content
  resp = MagicMock()
  resp.choices = [choice]
  resp.usage = None
  return resp


def _mock_openai(content: str = "Hello from Overview AI"):
  """Return a patch that makes import_module('openai') return a fake module."""
  mock_client = MagicMock()
  mock_client.chat.completions.create.return_value = _make_openai_response(content)

  fake_openai_module = MagicMock()
  fake_openai_module.OpenAI = MagicMock(return_value=mock_client)
  fake_openai_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
  fake_openai_module.RateLimitError = type("RateLimitError", (Exception,), {})
  fake_openai_module.APITimeoutError = type("APITimeoutError", (Exception,), {})
  fake_openai_module.BadRequestError = type("BadRequestError", (Exception,), {})

  return patch(
    "open_fdd.platform.api.ai_agent.import_module",
    return_value=fake_openai_module,
  )


def test_ai_agent_requires_api_key():
  """When Open‑Claw is not configured, the endpoint returns 503."""
  r = client.post(
    "/ai/agent",
    json={"mode": "overview_chat", "message": "How is the HVAC running?"},
  )
  assert r.status_code == 503


def test_ai_agent_overview_chat_success():
  """Happy path: overview_chat returns an answer, context, plots, tables, point_plots, table_fault_results."""
  fake_plots = {"site_id": None, "period": {"start": "2025-01-01", "end": "2025-01-08"}, "bucket": "day", "series": []}
  fake_tables = {"site_id": None, "period": {"start": "2025-01-01", "end": "2025-01-08"}, "by_equipment": []}
  fake_point_plots = {"period": {"start": "2025-01-01", "end": "2025-01-08"}, "series": [], "point_labels": {}}
  fake_fault_results = {"rows": [], "count": 0}
  with patch.dict(
    "os.environ",
    {
      "OFDD_OPEN_CLAW_BASE_URL": "http://openclaw.test/v1",
      "OFDD_OPEN_CLAW_API_KEY": "sk-openclaw-test",
    },
    clear=False,
  ), patch(
    "open_fdd.platform.api.ai_agent._build_overview_context",
    return_value={"data_model": {"site_count": 1}},
  ), patch(
    "open_fdd.platform.api.ai_agent.fetch_fault_timeseries_data",
    return_value=fake_plots,
  ), patch(
    "open_fdd.platform.api.ai_agent.fetch_faults_by_equipment_data",
    return_value=fake_tables,
  ), patch(
    "open_fdd.platform.api.ai_agent.get_point_ids_for_agent",
    return_value=["point-1", "point-2"],
  ), patch(
    "open_fdd.platform.api.ai_agent.fetch_point_timeseries_data",
    return_value=fake_point_plots,
  ), patch(
    "open_fdd.platform.api.ai_agent.fetch_fault_results_sample",
    return_value=fake_fault_results,
  ), _mock_openai("System looks healthy overall."):
    r = client.post(
      "/ai/agent",
      json={
        "mode": "overview_chat",
        "message": "How is the HVAC running?",
        "include_context": True,
      },
    )
  assert r.status_code == 200
  data = r.json()
  assert data["mode"] == "overview_chat"
  assert "answer" in data
  assert "System looks healthy" in data["answer"]
  assert "context" in data
  assert data["context"]["data_model"]["site_count"] == 1
  assert "plots" in data
  assert data["plots"]["bucket"] == "day"
  assert "tables" in data
  assert data["tables"]["by_equipment"] == []
  assert "point_plots" in data
  assert "table_fault_results" in data
  assert data["table_fault_results"]["count"] == 0


def test_ai_agent_rejects_unknown_mode():
  """Unsupported modes should return 400."""
  r = client.post(
    "/ai/agent",
    json={
      "mode": "unknown_mode",
      "message": "Test",
    },
  )
  assert r.status_code == 400
  data = r.json()
  assert data["error"]["code"] == "ERROR"
  assert "Unsupported mode" in data["error"]["message"]


def test_ai_agent_invalid_openai_key():
  """AuthenticationError from OpenAI should map to 401."""
  from open_fdd.platform.api.ai_agent import AiAgentError

  with patch.dict(
    "os.environ",
    {
      "OFDD_OPEN_CLAW_BASE_URL": "http://openclaw.test/v1",
      "OFDD_OPEN_CLAW_API_KEY": "sk-openclaw-test",
    },
    clear=False,
  ), patch(
    "open_fdd.platform.api.ai_agent._call_openai_chat",
    side_effect=AiAgentError(401, "Invalid OpenAI API key. Check your key and try again."),
  ):
    r = client.post(
      "/ai/agent",
      json={
        "mode": "overview_chat",
        "message": "How is the HVAC running?",
      },
    )
  assert r.status_code == 401
  data = r.json()
  assert data["error"]["code"] == "UNAUTHORIZED"
  assert "Invalid OpenAI API key" in data["error"]["message"]

