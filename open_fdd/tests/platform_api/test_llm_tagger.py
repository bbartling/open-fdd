"""Tests for POST /data-model/tag-with-openai endpoint and llm_tagger service."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)

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
    mock_client.chat.completions.create.return_value = _make_openai_response(openai_content)

    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI = MagicMock(return_value=mock_client)
    fake_openai_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
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
    assert r.status_code == 422  # Pydantic validation error — required field missing


# ---------------------------------------------------------------------------
# Endpoint: successful dry-run (auto_import=false)
# ---------------------------------------------------------------------------


def test_tag_with_openai_dry_run_success():
    export_patch, openai_patch = _mock_export_and_openai()
    with export_patch, openai_patch:
        r = client.post(
            "/data-model/tag-with-openai",
            json={"openai_api_key": "sk-test", "model": "gpt-4o", "auto_import": False},
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
    with export_patch, openai_patch:
        with patch(
            "open_fdd.platform.api.data_model.import_data_model",
            return_value={"created": 0, "updated": 1, "total": 1},
        ):
            r = client.post(
                "/data-model/tag-with-openai",
                json={"openai_api_key": "sk-test", "model": "gpt-4o", "auto_import": True},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["meta"]["import_result"]["total"] == 1


# ---------------------------------------------------------------------------
# Endpoint: malformed JSON from OpenAI → 422
# ---------------------------------------------------------------------------


def test_tag_with_openai_malformed_llm_json():
    export_patch, openai_patch = _mock_export_and_openai("This is not JSON at all.")
    with export_patch, openai_patch:
        r = client.post(
            "/data-model/tag-with-openai",
            json={"openai_api_key": "sk-test", "model": "gpt-4o"},
        )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Endpoint: invalid OpenAI key → 401
# ---------------------------------------------------------------------------


def test_tag_with_openai_invalid_key():
    from open_fdd.platform.llm_tagger import LlmTaggerError

    export_patch, _openai_patch = _mock_export_and_openai()
    with export_patch, patch(
        "open_fdd.platform.llm_tagger.tag_with_openai",
        side_effect=LlmTaggerError(401, "Invalid OpenAI API key. Check your key and try again."),
    ):
        r = client.post(
            "/data-model/tag-with-openai",
            json={"openai_api_key": "sk-bad", "model": "gpt-4o"},
        )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint: OpenAI timeout → 504
# ---------------------------------------------------------------------------


def test_tag_with_openai_timeout():
    from open_fdd.platform.llm_tagger import LlmTaggerError

    export_patch, _openai_patch = _mock_export_and_openai()
    with export_patch, patch(
        "open_fdd.platform.llm_tagger.tag_with_openai",
        side_effect=LlmTaggerError(504, "OpenAI API timed out after 120s."),
    ):
        r = client.post(
            "/data-model/tag-with-openai",
            json={"openai_api_key": "sk-test", "model": "gpt-4o"},
        )
    assert r.status_code == 504


# ---------------------------------------------------------------------------
# llm_tagger: missing openai package → 500
# ---------------------------------------------------------------------------


def test_llm_tagger_missing_openai_package():
    """If openai is not installed, tag_with_openai raises LlmTaggerError(500)."""
    from open_fdd.platform import llm_tagger
    from open_fdd.platform.llm_tagger import LlmTaggerError

    with patch("open_fdd.platform.llm_tagger.import_module", side_effect=ImportError("No module named 'openai'")):
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
