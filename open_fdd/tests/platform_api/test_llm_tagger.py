"""Tests for POST /data-model/tag-with-openai endpoint and llm_tagger service."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)

OPENCLAW_ENV = {
    "OFDD_OPEN_CLAW_BASE_URL": "http://openclaw.test/v1",
    "OFDD_OPEN_CLAW_API_KEY": "sk-openclaw-test",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_IMPORT_PAYLOAD = {
    "points": [
        {
            "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            "site_id": "b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22",
            "external_id": "SA-T",
            "brick_type": "Supply_Air_Temperature_Sensor",
            "rule_input": "ahu_sat",
            "unit": "degF",
            "polling": True,
            "equipment_name": "AHU-1",
        }
    ],
    "equipment": [],
}

MOCK_OPENAI_CONTENT = json.dumps(VALID_IMPORT_PAYLOAD)


def _make_openai_response(content: str) -> MagicMock:
    """Build a minimal mock matching openai.ChatCompletion response shape."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _mock_export_and_openai(openai_content: str = MOCK_OPENAI_CONTENT):
    """Context managers: empty DB export + mocked dynamic openai module."""
    export_patch = patch(
        "open_fdd.platform.api.data_model._build_unified_export",
        return_value=[],
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_response(
        openai_content
    )

    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI = MagicMock(return_value=mock_client)
    fake_openai_module.AuthenticationError = type(
        "AuthenticationError", (Exception,), {}
    )
    fake_openai_module.RateLimitError = type("RateLimitError", (Exception,), {})
    fake_openai_module.APITimeoutError = type("APITimeoutError", (Exception,), {})
    fake_openai_module.BadRequestError = type("BadRequestError", (Exception,), {})

    openai_patch = patch(
        "open_fdd.platform.llm_tagger.import_module",
        return_value=fake_openai_module,
    )
    return export_patch, openai_patch


# ---------------------------------------------------------------------------
# Endpoint: missing api key
# ---------------------------------------------------------------------------


def test_tag_with_openai_requires_api_key():
    r = client.post(
        "/data-model/tag-with-openai",
        json={"model": "gpt-4o"},  # openai_api_key omitted
    )
    assert r.status_code == 503  # AI disabled (Open‑Claw not configured)


# ---------------------------------------------------------------------------
# Endpoint: successful dry-run (auto_import=false)
# ---------------------------------------------------------------------------


def test_tag_with_openai_dry_run_success():
    export_patch, openai_patch = _mock_export_and_openai()
    with patch.dict(os.environ, OPENCLAW_ENV, clear=False), export_patch, openai_patch:
        r = client.post(
            "/data-model/tag-with-openai",
            json={"model": "gpt-4o", "auto_import": False},
        )
    assert r.status_code == 200
    data = r.json()
    assert "points" in data
    assert "equipment" in data
    assert data["meta"]["model"] == "gpt-4o"
    assert data["meta"]["point_count"] == 1
    # Should NOT have import_result since auto_import=false
    assert "import_result" not in data["meta"]


# ---------------------------------------------------------------------------
# Endpoint: auto_import=true calls import_data_model
# ---------------------------------------------------------------------------


def test_tag_with_openai_auto_import():
    export_patch, openai_patch = _mock_export_and_openai()
    with patch.dict(os.environ, OPENCLAW_ENV, clear=False), export_patch, openai_patch:
        with patch(
            "open_fdd.platform.api.data_model.import_data_model",
            return_value={"created": 0, "updated": 1, "total": 1},
        ):
            r = client.post(
                "/data-model/tag-with-openai",
                json={"model": "gpt-4o", "auto_import": True},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["meta"]["import_result"]["total"] == 1


# ---------------------------------------------------------------------------
# Endpoint: malformed JSON from OpenAI → 422
# ---------------------------------------------------------------------------


def test_tag_with_openai_malformed_llm_json():
    export_patch, openai_patch = _mock_export_and_openai("This is not JSON at all.")
    with patch.dict(os.environ, OPENCLAW_ENV, clear=False), export_patch, openai_patch:
        r = client.post(
            "/data-model/tag-with-openai",
            json={"model": "gpt-4o"},
        )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Endpoint: invalid OpenAI key → 401
# ---------------------------------------------------------------------------


def test_tag_with_openai_invalid_key():
    from open_fdd.platform.llm_tagger import LlmTaggerError

    export_patch, _openai_patch = _mock_export_and_openai()
    with patch.dict(os.environ, OPENCLAW_ENV, clear=False), export_patch, patch(
        "open_fdd.platform.llm_tagger.tag_with_openai",
        side_effect=LlmTaggerError(
            401, "Invalid OpenAI API key. Check your key and try again."
        ),
    ):
        r = client.post(
            "/data-model/tag-with-openai",
            json={"model": "gpt-4o"},
        )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint: OpenAI timeout → 504
# ---------------------------------------------------------------------------


def test_tag_with_openai_timeout():
    from open_fdd.platform.llm_tagger import LlmTaggerError

    export_patch, _openai_patch = _mock_export_and_openai()
    with patch.dict(os.environ, OPENCLAW_ENV, clear=False), export_patch, patch(
        "open_fdd.platform.llm_tagger.tag_with_openai",
        side_effect=LlmTaggerError(504, "OpenAI API timed out after 120s."),
    ):
        r = client.post(
            "/data-model/tag-with-openai",
            json={"model": "gpt-4o"},
        )
    assert r.status_code == 504


# ---------------------------------------------------------------------------
# Endpoint: openai not installed → 500 with JSON message
# ---------------------------------------------------------------------------


def test_tag_with_openai_openai_not_installed_returns_500():
    """When openai package is missing, endpoint returns 500 with error.message (install hint)."""
    from open_fdd.platform.llm_tagger import LlmTaggerError

    export_patch, _ = _mock_export_and_openai()
    with (
        patch.dict(os.environ, OPENCLAW_ENV, clear=False),
        export_patch,
        patch(
            "open_fdd.platform.llm_tagger.tag_with_openai",
            side_effect=LlmTaggerError(
                500,
                "openai package is not installed. Add it with: pip install 'openai>=1.0'",
            ),
        ),
    ):
        r = client.post(
            "/data-model/tag-with-openai",
            json={"model": "gpt-4o"},
        )
    assert r.status_code == 500
    data = r.json()
    assert "error" in data
    assert "message" in data["error"]
    assert "openai" in data["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Endpoint: uncaught exception → 500 with JSON message (catch-all)
# ---------------------------------------------------------------------------


def test_tag_with_openai_uncaught_exception_returns_500_with_message():
    """When the endpoint raises a non-HTTPException (e.g. from export), we return 500 with a message."""
    export_patch, _ = _mock_export_and_openai()
    with patch.dict(os.environ, OPENCLAW_ENV, clear=False), export_patch, patch(
        "open_fdd.platform.api.data_model._build_unified_export",
        side_effect=RuntimeError("DB connection failed"),
    ):
        r = client.post(
            "/data-model/tag-with-openai",
            json={"model": "gpt-4o"},
        )
    assert r.status_code == 500
    data = r.json()
    assert "error" in data
    assert "message" in data["error"]
    assert "DB connection failed" in data["error"]["message"] or "RuntimeError" in data["error"]["message"]


# ---------------------------------------------------------------------------
# llm_tagger: missing openai package → 500
# ---------------------------------------------------------------------------


def test_llm_tagger_missing_openai_package():
    """If openai is not installed, tag_with_openai raises LlmTaggerError(500)."""
    from open_fdd.platform import llm_tagger
    from open_fdd.platform.llm_tagger import LlmTaggerError

    with patch(
        "open_fdd.platform.llm_tagger.import_module",
        side_effect=ImportError("No module named 'openai'"),
    ):
        with pytest.raises(LlmTaggerError) as exc_info:
            llm_tagger.tag_with_openai([], api_key="sk-test")
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# llm_tagger: empty api_key → 400
# ---------------------------------------------------------------------------


def test_llm_tagger_empty_key_raises_400():
    from open_fdd.platform.llm_tagger import tag_with_openai
    from open_fdd.platform.llm_tagger import LlmTaggerError

    with pytest.raises(LlmTaggerError) as exc_info:
        tag_with_openai([], api_key="   ")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# llm_tagger: retry with prompt chaining (validation error in next prompt)
# ---------------------------------------------------------------------------


def test_llm_tagger_retry_with_prompt_chain_succeeds_on_second_attempt():
    """First response fails schema validation; second attempt gets error in prompt and returns valid JSON."""
    from open_fdd.platform import llm_tagger

    # Invalid: point_id as int (Pydantic expects str)
    invalid_payload = {
        "points": [
            {
                "point_id": 123,
                "site_id": "b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22",
                "external_id": "SA-T",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "rule_input": "ahu_sat",
                "unit": "degF",
                "polling": True,
                "equipment_name": "AHU-1",
            }
        ],
        "equipment": [],
    }
    valid_payload = {
        "points": [{**invalid_payload["points"][0], "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"}],
        "equipment": [],
    }

    export_patch, _openai_patch = _mock_export_and_openai()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        _make_openai_response(json.dumps(invalid_payload)),
        _make_openai_response(json.dumps(valid_payload)),
    ]
    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI = MagicMock(return_value=mock_client)
    fake_openai_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    fake_openai_module.RateLimitError = type("RateLimitError", (Exception,), {})
    fake_openai_module.APITimeoutError = type("APITimeoutError", (Exception,), {})
    fake_openai_module.BadRequestError = type("BadRequestError", (Exception,), {})

    with export_patch, patch(
        "open_fdd.platform.llm_tagger.import_module",
        return_value=fake_openai_module,
    ):
        body, _usage, agent_log = llm_tagger.tag_with_openai(
            [{"point_id": invalid_payload["points"][0]["point_id"], "site_id": invalid_payload["points"][0]["site_id"], "external_id": "SA-T", "bacnet_device_id": "1", "object_identifier": "ai,1"}],
            api_key="sk-test",
            max_retries=3,
        )
    assert body.points
    assert len(agent_log) >= 4  # attempt 1, validation_failed, attempt 2, success
    steps = [e["step"] for e in agent_log]
    assert "attempt" in steps
    assert "validation_failed" in steps
    assert "success" in steps
    assert mock_client.chat.completions.create.call_count == 2
    # Second call should include previous error in user message (prompt chaining)
    second_call_messages = mock_client.chat.completions.create.call_args_list[1][1]["messages"]
    user_messages = [m for m in second_call_messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert "Previous attempt failed" in user_messages[0]["content"]


def test_llm_tagger_retry_exhausted_returns_422():
    """All attempts fail schema validation; last attempt raises LlmTaggerError(422)."""
    from open_fdd.platform.llm_tagger import LlmTaggerError, tag_with_openai

    # point_id as int fails validation (must be str)
    invalid_payload = {"points": [{"point_id": 123}], "equipment": []}

    export_patch, _openai_patch = _mock_export_and_openai(json.dumps(invalid_payload))
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_openai_response(
        json.dumps(invalid_payload)
    )
    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI = MagicMock(return_value=mock_client)
    fake_openai_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    fake_openai_module.RateLimitError = type("RateLimitError", (Exception,), {})
    fake_openai_module.APITimeoutError = type("APITimeoutError", (Exception,), {})
    fake_openai_module.BadRequestError = type("BadRequestError", (Exception,), {})

    with export_patch, patch(
        "open_fdd.platform.llm_tagger.import_module",
        return_value=fake_openai_module,
    ):
        with pytest.raises(LlmTaggerError) as exc_info:
            tag_with_openai(
                [{}],
                api_key="sk-test",
                max_retries=2,
            )
    assert exc_info.value.status_code == 422
    assert "attempts" in (exc_info.value.detail or "").lower() or "validation" in (exc_info.value.detail or "").lower()
