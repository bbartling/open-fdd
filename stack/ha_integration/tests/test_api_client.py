"""Tests for Open-FDD HA integration api_client. Uses mocked aiohttp."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Load api_client without importing the rest of the integration (which needs homeassistant)
_api_client_path = Path(__file__).resolve().parent.parent / "custom_components" / "openfdd" / "api_client.py"
_spec = importlib.util.spec_from_file_location("api_client", _api_client_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
OpenFDDClient = _mod.OpenFDDClient


def _run(coro):
    return asyncio.run(coro)


def _mock_response(status=200, json_data=None, text_data=None):
    resp = AsyncMock()
    resp.status = status
    resp.content_length = len(text_data or "") if text_data else (len(str(json_data or "")) or 1)
    resp.raise_for_status = MagicMock()
    if status >= 400:
        from aiohttp import ClientResponseError
        resp.raise_for_status.side_effect = ClientResponseError(MagicMock(), MagicMock())
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    else:
        resp.json = AsyncMock(side_effect=Exception("not json"))
    if text_data is not None:
        resp.text = AsyncMock(return_value=text_data)
    return resp


def _mock_session_request(*args, **kwargs):
    """Return an async context manager that yields a mock response."""
    class Ctx:
        async def __aenter__(self):
            return _mock_response(200, json_data={"status": "ok"})
        async def __aexit__(self, *a):
            pass
    return Ctx()


def _make_mock_session(request_return=None):
    if request_return is None:
        request_return = _mock_session_request()
    mock_sess = MagicMock()
    mock_sess.request = MagicMock(return_value=request_return)
    return mock_sess


def test_client_init_strips_trailing_slash():
    client = OpenFDDClient(base_url="http://host:8000/", api_key="key")
    assert client.base_url == "http://host:8000"
    assert client._headers["Authorization"] == "Bearer key"


def test_get_health():
    client = OpenFDDClient(base_url="http://localhost:8000", api_key="secret")
    with patch("aiohttp.ClientSession") as session_klass:
        session_klass.return_value.__aenter__ = AsyncMock(return_value=_make_mock_session())
        session_klass.return_value.__aexit__ = AsyncMock(return_value=None)
        result = _run(client.get_health())
    assert result == {"status": "ok"}


def test_get_capabilities():
    client = OpenFDDClient(base_url="http://localhost:8000", api_key="secret")
    with patch("aiohttp.ClientSession") as session_klass:
        session_klass.return_value.__aenter__ = AsyncMock(return_value=_make_mock_session())
        session_klass.return_value.__aexit__ = AsyncMock(return_value=None)
        result = _run(client.get_capabilities())
    assert result == {"status": "ok"}


def test_get_faults_active_with_params():
    client = OpenFDDClient(base_url="http://localhost:8000", api_key="secret")
    req_kw = {}

    def capture_request(*args, **kwargs):
        req_kw.update(kwargs)
        return _mock_session_request()

    mock_sess = MagicMock()
    mock_sess.request = MagicMock(side_effect=capture_request)
    with patch("aiohttp.ClientSession") as session_klass:
        session_klass.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        session_klass.return_value.__aexit__ = AsyncMock(return_value=None)
        _run(client.get_faults_active(site_id="site-1", equipment_id="eq-1"))
    assert req_kw.get("params") == {"site_id": "site-1", "equipment_id": "eq-1"}


def test_ws_url():
    client = OpenFDDClient(base_url="http://localhost:8000", api_key="token")
    assert client.ws_url() == "ws://localhost:8000/ws/events?token=token"


def test_list_sites():
    client = OpenFDDClient(base_url="http://api:8000", api_key="k")
    with patch("aiohttp.ClientSession") as session_klass:
        session_klass.return_value.__aenter__ = AsyncMock(return_value=_make_mock_session())
        session_klass.return_value.__aexit__ = AsyncMock(return_value=None)
        result = _run(client.list_sites())
    assert result == {"status": "ok"}


def test_create_site_sends_body():
    client = OpenFDDClient(base_url="http://api:8000", api_key="k")
    req_kw = {}

    def capture_request(*args, **kwargs):
        req_kw.update(kwargs)
        return _mock_session_request()

    mock_sess = MagicMock()
    mock_sess.request = MagicMock(side_effect=capture_request)
    with patch("aiohttp.ClientSession") as session_klass:
        session_klass.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        session_klass.return_value.__aexit__ = AsyncMock(return_value=None)
        _run(client.create_site(name="MySite", description="A site"))
    assert req_kw.get("json") == {"name": "MySite", "description": "A site"}
    assert "/sites" in str(mock_sess.request.call_args[0][1])


def test_get_data_model_ttl_returns_text():
    client = OpenFDDClient(base_url="http://api:8000", api_key="k")
    ttl_content = "@prefix brick: <https://brickschema.org/schema/Brick#> ."

    def mock_request(*args, **kwargs):
        resp = _mock_response(200, text_data=ttl_content)
        resp.content_length = len(ttl_content)
        resp.json = AsyncMock(side_effect=Exception("not json"))
        resp.text = AsyncMock(return_value=ttl_content)
        class Ctx:
            async def __aenter__(self):
                return resp
            async def __aexit__(self, *a):
                pass
        return Ctx()

    mock_sess = MagicMock()
    mock_sess.request = MagicMock(side_effect=mock_request)
    with patch("aiohttp.ClientSession") as session_klass:
        session_klass.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        session_klass.return_value.__aexit__ = AsyncMock(return_value=None)
        result = _run(client.get_data_model_ttl(site_id=None, save=True))
    assert result == ttl_content
