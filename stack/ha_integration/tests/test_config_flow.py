"""Tests for Open-FDD HA integration config flow.

Config flow validation: when API requires auth (401 without Bearer), the client must send
Authorization: Bearer <api_key>. These tests verify the api_client sends the header so that
config_flow (which uses OpenFDDClient) can succeed when the user enters the correct key.
"""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("aiohttp", reason="HA integration tests require aiohttp")

_api_client_path = Path(__file__).resolve().parent.parent / "custom_components" / "openfdd" / "api_client.py"
_spec = importlib.util.spec_from_file_location("api_client", _api_client_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
OpenFDDClient = _mod.OpenFDDClient


def _run(coro):
    return asyncio.run(coro)


def test_client_raises_on_401_without_auth():
    """When server returns 401 (auth required), client raises ClientResponseError so config_flow can show auth_required or invalid_auth."""
    from aiohttp import ClientResponseError

    def mock_401(*args, **kwargs):
        req = MagicMock()
        req.url = "http://localhost:8000/capabilities"
        exc = ClientResponseError(req, (), status=401, message="Unauthorized")
        resp = MagicMock()
        resp.status = 401
        resp.raise_for_status = MagicMock(side_effect=exc)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        return resp

    client = OpenFDDClient(base_url="http://localhost:8000", api_key="")
    with patch("aiohttp.ClientSession") as session_klass:
        mock_sess = MagicMock()
        mock_sess.request = MagicMock(side_effect=mock_401)
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        session_klass.return_value = mock_sess

        with pytest.raises(ClientResponseError) as exc_info:
            _run(client.get_capabilities())
        assert exc_info.value.status == 401


def test_client_succeeds_with_bearer_when_server_requires_auth():
    """When server requires auth, request with correct Bearer header returns 200; config_flow creates entry."""
    def mock_200(*args, **kwargs):
        resp = MagicMock()
        resp.status = 200
        resp.content_length = 1
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={"version": "2.0.2"})
        resp.text = AsyncMock(return_value="")
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        return resp

    client = OpenFDDClient(base_url="http://localhost:8000", api_key="e8da2602da3ce5ddde45d46d772508445006c6ef2b503f9dce0828801d00957f")
    req_kw = {}

    def capture_and_200(*args, **kwargs):
        req_kw.update(kwargs)
        return mock_200()

    with patch("aiohttp.ClientSession") as session_klass:
        mock_sess = MagicMock()
        mock_sess.request = MagicMock(side_effect=capture_and_200)
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        session_klass.return_value = mock_sess

        result = _run(client.get_capabilities())
    assert result == {"version": "2.0.2"}
    assert req_kw.get("headers", {}).get("Authorization") == "Bearer e8da2602da3ce5ddde45d46d772508445006c6ef2b503f9dce0828801d00957f"
