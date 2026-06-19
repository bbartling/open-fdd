"""Niagara baskStream connector tests (SCRAM, discovery, routes, poll worker)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import msgpack
import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.niagara_baskstream_client import (  # noqa: E402
    AsyncNiagaraBaskStreamClient,
    NiagaraBaskStreamError,
    _CookieJar,
    friendly_error,
)
from openfdd_bridge.niagara_discovery import (  # noqa: E402
    discover_from_tree_rows,
    is_point,
    is_proxy_extension,
    normalize_point_record,
    normalize_read_value,
    should_follow_child,
)
from openfdd_bridge.niagara_scram import client_final_proof, parse_scram, prep_username  # noqa: E402
from openfdd_bridge.niagara_store import (  # noqa: E402
    delete_station,
    get_station,
    list_stations,
    make_point_id,
    upsert_station,
)


@pytest.fixture
def authed_client(raw_client: TestClient) -> TestClient:
    return raw_client


# --- SCRAM ---


def test_prep_username_escapes_equals_and_comma():
    assert prep_username("a=b,c") == "a=3Db=2Cc"


def test_parse_scram_server_first():
    parsed = parse_scram("r=abc123,s=YWJj,i=4096")
    assert parsed["r"] == "abc123"
    assert parsed["s"] == "YWJj"
    assert parsed["i"] == "4096"


def test_client_final_proof_rejects_bad_nonce():
    with pytest.raises(ValueError, match="Bad SCRAM"):
        client_final_proof(
            username="admin",
            client_nonce="client",
            server_first="r=other,s=YWJj,i=4096",
            password="secret",
        )


def test_client_final_proof_deterministic():
    username = "admin"
    password = "Station9065!"
    client_nonce = "fixedClientNonce12"
    salt = base64.b64encode(b"saltbytes123456").decode("ascii")
    server_first = f"r={client_nonce}serverSuffix,s={salt},i=4096"
    _, proof_b64 = client_final_proof(
        username=username,
        client_nonce=client_nonce,
        server_first=server_first,
        password=password,
    )
    # Recompute expected proof
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), 4096, dklen=32)
    client_first_bare = f"n={prep_username(username)},r={client_nonce}"
    client_final_no_proof = f"c=biws,r={client_nonce}serverSuffix"
    auth_message = f"{client_first_bare},{server_first},{client_final_no_proof}"
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    client_signature = hmac.new(stored_key, auth_message.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(bytes(a ^ b for a, b in zip(client_key, client_signature))).decode("ascii")
    assert proof_b64 == expected


# --- Cookies ---


def test_cookie_jar_captures_multiple_set_cookie():
    jar = _CookieJar()

    class _Hdr:
        def getall(self, _k, default=()):
            return ("JSESSIONID=abc; Path=/", "niagara=xyz; Path=/")

    resp = SimpleNamespace(headers=_Hdr())
    jar.store_response(resp)
    assert "JSESSIONID=abc" in jar.header()
    assert "niagara=xyz" in jar.header()


# --- Protocol / msgpack ---


async def _call_correlates_by_id_async():
    client = AsyncNiagaraBaskStreamClient("https://example.test", verify_tls=False)
    sent: list[bytes] = []

    async def fake_send(data):
        sent.append(data)

    other_frame = msgpack.packb({"op": "ping", "id": "other", "ok": True}, use_bin_type=True)
    target_frame = msgpack.packb({"op": "ping", "id": "req-1", "pong": True}, use_bin_type=True)

    class _Msg:
        type = 2  # BINARY — patched below

    ws = AsyncMock()
    ws.closed = False

    import aiohttp

    messages = [
        SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=other_frame),
        SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=target_frame),
    ]

    async def recv(**_kwargs):
        return messages.pop(0)

    ws.send_bytes = fake_send
    ws.receive = recv
    client._ws = ws
    client._cookies._cookies = {"s": "1"}

    with patch.object(client, "connect_ws", new=AsyncMock()):
        out = await client.call("ping", id="req-1")
    assert out["pong"] is True
    unpacked = msgpack.unpackb(sent[0], raw=False)
    assert unpacked["id"] == "req-1"


def test_call_correlates_by_id():
    asyncio.run(_call_correlates_by_id_async())


async def _call_raises_on_error_frame_async():
    client = AsyncNiagaraBaskStreamClient("https://example.test", verify_tls=False)
    err_frame = msgpack.packb({"op": "error", "id": "x1", "error": "bad ord"}, use_bin_type=True)

    import aiohttp

    ws = AsyncMock()
    ws.closed = False
    ws.send_bytes = AsyncMock()
    ws.receive = AsyncMock(
        return_value=SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=err_frame),
    )
    client._ws = ws
    client._cookies._cookies = {"s": "1"}

    with patch.object(client, "connect_ws", new=AsyncMock()):
        await client.call("read", id="x1", points=["slot:/x"])


def test_call_raises_on_error_frame():
    with pytest.raises(NiagaraBaskStreamError):
        asyncio.run(_call_raises_on_error_frame_async())


def test_friendly_error_tls():
    msg = friendly_error(Exception("SSL certificate verify failed"), station_url="https://x")
    assert "TLS" in msg or "self-signed" in msg


# --- Discovery ---


def test_should_follow_child_skips_external_slot_by_default():
    base = "slot:/Drivers/BacnetNetwork/DEV/points"
    assert should_follow_child(base, "slot:/", follow_external=False) is False
    assert should_follow_child(base, "slot:/", follow_external=True) is True


def test_should_follow_child_preserves_ord_encoding():
    ord_value = "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dT"
    assert "$20" in ord_value
    assert "$2d" in ord_value
    assert should_follow_child("slot:/Drivers", ord_value, follow_external=False) is True


def test_proxy_extension_classification():
    proxy = {
        "slotPath": "slot:/Drivers/p/C04$2dDRY$2dC/proxyExt",
        "display": "Proxy Ext",
        "typeSpec": "bacnet:BacnetBooleanProxyExt",
        "metadata": {"classification": {"isPoint": True}},
    }
    point = {
        "slotPath": "slot:/Drivers/p/OA$2dT",
        "display": "OA-T",
        "typeSpec": "control:NumericPoint",
        "metadata": {"classification": {"isPoint": True}},
    }
    assert is_proxy_extension(proxy)
    assert is_point(proxy, include_proxy_ext=False) is False
    assert is_point(point, include_proxy_ext=False) is True


def test_discover_from_tree_rows_excludes_proxy_by_default():
    rows = [
        (0, {"slotPath": "slot:/p/A", "display": "A", "metadata": {"classification": {"isPoint": True}}}),
        (
            1,
            {
                "slotPath": "slot:/p/A/proxyExt",
                "display": "Proxy Ext",
                "typeSpec": "bacnet:BacnetBooleanProxyExt",
                "metadata": {"classification": {"isPoint": True}},
            },
        ),
    ]
    out = discover_from_tree_rows(rows, include_proxy_ext=False)
    assert len(out) == 1
    assert out[0]["slotPath"] == "slot:/p/A"


def test_normalize_read_value_display_fallback():
    row = normalize_read_value(
        {"point": "slot:/x", "value": 72.5, "status": "{ok}"},
        station_id="bench",
        meta={"display": "OA-T"},
    )
    assert row["value"] == 72.5
    assert row["display_value"] == 72.5
    assert row["source"] == "niagara_baskstream"


def test_make_point_id_stable():
    pid = make_point_id("bench", "slot:/Drivers/BENS$20BOX/OA$2dT")
    assert "niagara-bench-" in pid
    assert "$" not in pid


# --- Store / routes ---


def test_station_crud_no_plaintext_password(monkeypatch):
    monkeypatch.setenv("OPENFDD_NIAGARA_ADMIN_PASSWORD", "secret")
    station = upsert_station(
        {
            "name": "Bench",
            "station_url": "https://192.168.204.11",
            "username": "admin",
            "password_env": "OPENFDD_NIAGARA_ADMIN_PASSWORD",
            "password": "must-not-persist",
        }
    )
    from openfdd_bridge.niagara_store import niagara_stations_path

    raw = json.loads(niagara_stations_path().read_text())
    assert "password" not in raw["stations"][0]
    row = get_station(station["id"])
    assert row is not None
    assert row.get("password_configured") is True
    delete_station(station["id"])


def test_niagara_health_route(authed_client: TestClient, operator_headers: dict[str, str]):
    r = authed_client.get("/api/niagara/health", headers=operator_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["read_only"] is True
    assert body["connector"] == "niagara_baskstream"


def test_niagara_test_connection_mocked(authed_client: TestClient, operator_headers: dict[str, str], monkeypatch):
    monkeypatch.setenv("OPENFDD_NIAGARA_ADMIN_PASSWORD", "x")
    station = upsert_station(
        {
            "name": "Mock",
            "station_url": "https://example.test",
            "username": "admin",
        }
    )

    async def fake_test(sid: str):
        assert sid == station["id"]
        return {"ok": True, "authenticated_user": "admin"}

    monkeypatch.setattr("openfdd_bridge.routes.niagara_routes.test_station", fake_test)
    r = authed_client.post(
        f"/api/niagara/stations/{station['id']}/test",
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert r.json()["authenticated_user"] == "admin"


def test_niagara_discover_mocked(authed_client: TestClient, operator_headers: dict[str, str], monkeypatch):
    station = upsert_station(
        {"name": "D", "station_url": "https://example.test", "username": "u"},
    )

    async def fake_discover(sid, **kwargs):
        return {
            "station_id": sid,
            "base": "slot:/Drivers",
            "count": 1,
            "points": [
                normalize_point_record(
                    {"slotPath": "slot:/p/OA$2dT", "display": "OA-T", "metadata": {"classification": {"isPoint": True}}},
                    station_id=sid,
                    station_name="D",
                )
            ],
        }

    monkeypatch.setattr("openfdd_bridge.routes.niagara_routes.discover_points", fake_discover)
    r = authed_client.post(
        f"/api/niagara/stations/{station['id']}/discover",
        json={},
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert "$2d" in r.json()["points"][0]["point_ord"]


# --- Poll worker ---


def test_poll_worker_skips_disabled_station(monkeypatch):
    station = upsert_station(
        {
            "name": "Off",
            "station_url": "https://example.test",
            "username": "u",
            "enabled": False,
        }
    )
    from openfdd_bridge.niagara_store import set_poll_running
    from openfdd_bridge.niagara_poll_worker import _stations_due

    set_poll_running(station["id"], True)
    assert _stations_due() == []


def test_app_boot_with_unreachable_station(raw_client: TestClient):
    """create_app must not raise when Niagara is configured but down."""
    r = raw_client.get("/api/niagara/health")
    assert r.status_code in {200, 401, 403}


def test_poll_station_once_batches(monkeypatch):
    monkeypatch.setattr("openfdd_bridge.niagara_store.append_samples_and_ingest", lambda samples, **kw: {"samples": len(samples)})
    station = upsert_station(
        {
            "name": "Batch",
            "station_url": "https://example.test",
            "username": "u",
            "read_batch_size": 2,
            "password_env": "OPENFDD_NIAGARA_ADMIN_PASSWORD",
        }
    )
    monkeypatch.setenv("OPENFDD_NIAGARA_ADMIN_PASSWORD", "pw")
    from openfdd_bridge.niagara_store import save_points_cache

    save_points_cache(
        station["id"],
        [
            {"point_ord": f"slot:/p/{i}", "point_name": f"P{i}"} for i in range(3)
        ],
    )

    reads: list[list[str]] = []

    class _FakeClient:
        async def read(self, points):
            reads.append(list(points))
            return {
                "points": [
                    {"point": p, "value": 1, "displayValue": "1", "status": "{ok}"} for p in points
                ]
            }

        async def close(self):
            pass

    async def fake_login(st, *, persistent=True):
        return _FakeClient()

    monkeypatch.setattr("openfdd_bridge.niagara_service._login_client", fake_login)
    from openfdd_bridge.niagara_service import poll_station_once

    async def run():
        out = await poll_station_once(station["id"], persistent=False)
        assert out["samples"] == 3
        assert len(reads) == 2

    asyncio.run(run())


def test_upsert_preserves_commission_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("openfdd_bridge.niagara_store.niagara_stations_path", lambda: tmp_path / "stations.json")
    monkeypatch.setattr("openfdd_bridge.niagara_store._ensure_dirs", lambda: None)
    profile = {
        "version": 1,
        "buildings": [{"id": "b1", "label": "Building", "folder_ord": "slot:/Drivers/B1"}],
        "devices": [],
    }
    created = upsert_station(
        {
            "id": "prof-test",
            "name": "Profile Test",
            "station_url": "https://niagara.example.test",
            "username": "admin",
            "commission_profile": profile,
        }
    )
    assert created["commission_profile"]["buildings"][0]["id"] == "b1"
    updated = upsert_station(
        {
            "id": "prof-test",
            "name": "Profile Test Renamed",
            "station_url": "https://niagara.example.test",
            "username": "admin",
        }
    )
    assert updated["name"] == "Profile Test Renamed"
    assert updated["commission_profile"]["buildings"][0]["id"] == "b1"


def test_niagara_test_draft_route_validation(authed_client: TestClient, operator_headers: dict[str, str]):
    bad = authed_client.post(
        "/api/niagara/stations/test-draft",
        headers=operator_headers,
        json={"station_url": "ftp://bad", "username": "admin", "password": "x"},
    )
    assert bad.status_code == 422


def test_niagara_tree_route_mock(authed_client: TestClient, operator_headers: dict[str, str], monkeypatch):
    station = upsert_station(
        {
            "id": "tree-test",
            "name": "Tree Test",
            "station_url": "https://niagara.example.test",
            "username": "admin",
            "password_env": "OPENFDD_NIAGARA_ADMIN_PASSWORD",
            "enabled": True,
            "root_ord": "slot:/Drivers",
        }
    )

    async def fake_browse(station_id, *, base, depth=3, follow_external=None, **kwargs):
        return {
            "base": base,
            "count": 2,
            "nodes": [
                {"ord": f"{base}/BldgA", "name": "BldgA", "type": "folder", "parent_ord": base},
                {"ord": f"{base}/BldgB", "name": "BldgB", "type": "folder", "parent_ord": base},
            ],
            "truncated": False,
        }

    monkeypatch.setattr("openfdd_bridge.routes.niagara_routes.browse_tree", fake_browse)
    res = authed_client.get(
        f"/api/niagara/stations/{station['id']}/tree",
        params={"base": "slot:/Drivers", "depth": 3},
        headers=operator_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    assert body["nodes"][0]["name"] == "BldgA"
