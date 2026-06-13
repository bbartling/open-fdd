"""Async Niagara baskStream client (SCRAM login + MessagePack WebSocket)."""

from __future__ import annotations

import base64
import json
import logging
import os
import ssl
import uuid
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import quote, urlparse

import msgpack

from .niagara_scram import client_final_proof, prep_username

_log = logging.getLogger(__name__)

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional until deps installed
    aiohttp = None  # type: ignore


class NiagaraBaskStreamError(RuntimeError):
    """Niagara login, HTTP, or baskStream protocol failure."""


class NiagaraDepsMissing(NiagaraBaskStreamError):
    """aiohttp/msgpack not installed."""


def _require_aiohttp():
    if aiohttp is None:
        raise NiagaraDepsMissing(
            "Niagara connector requires aiohttp and msgpack; pip install -r workspace/api/requirements.txt"
        )


def friendly_error(exc: Exception, *, station_url: str) -> str:
    text = str(exc)
    lower = text.lower()
    if "certificate" in lower or "ssl" in lower:
        return (
            f"TLS error reaching {station_url}: {text}. "
            "For self-signed bench certs leave verify_tls=false."
        )
    if "403" in text:
        return f"Forbidden (403) — user lacks baskStream access on {station_url}."
    if "401" in text or "scram" in lower or "login" in lower:
        return f"Niagara login failed for {station_url}: check username/password_env."
    if "connection" in lower or "refused" in lower or "unreachable" in lower:
        return f"Cannot reach {station_url} — check firewall, host, and port 443."
    if "websocket" in lower or "ws" in lower:
        return f"WebSocket upgrade failed for {station_url}/stream: {text}"
    return text


class _CookieJar:
    def __init__(self) -> None:
        self._cookies: dict[str, str] = {}

    def store_response(self, response: "aiohttp.ClientResponse") -> None:
        for raw in response.headers.getall("Set-Cookie", ()):
            try:
                parsed = SimpleCookie()
                parsed.load(raw)
                for name, morsel in parsed.items():
                    self._cookies[name] = morsel.value
            except Exception:
                first = raw.split(";", 1)[0]
                if "=" in first:
                    name, value = first.split("=", 1)
                    self._cookies[name.strip()] = value.strip()

    def header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())


class AsyncNiagaraBaskStreamClient:
    """Read-only async baskStream client — one persistent WS per instance."""

    def __init__(
        self,
        station_url: str,
        *,
        verify_tls: bool = False,
        timeout_s: float = 45.0,
    ) -> None:
        _require_aiohttp()
        self.station_url = station_url.rstrip("/")
        self.verify_tls = verify_tls
        self.timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._cookies = _CookieJar()
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._authenticated_user: str | None = None

    def _ssl_context(self) -> bool | ssl.SSLContext:
        if self.verify_tls:
            return True
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context())
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
                headers={"User-Agent": "openfdd-niagara-connector/0.1", "Accept": "*/*"},
            )
        return self._session

    def _url(self, path: str) -> str:
        return f"{self.station_url}{path}"

    async def http(
        self,
        method: str,
        path: str,
        *,
        body: str | bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> aiohttp.ClientResponse:
        session = await self._ensure_session()
        req_headers = {}
        cookie_header = self._cookies.header()
        if cookie_header:
            req_headers["Cookie"] = cookie_header
        if headers:
            req_headers.update(headers)
        response = await session.request(
            method,
            self._url(path),
            data=body or b"",
            headers=req_headers,
            allow_redirects=False,
        )
        self._cookies.store_response(response)
        return response

    async def health(self) -> dict[str, Any] | None:
        response = await self.http("GET", "/stream/health")
        if response.status == 200:
            try:
                return await response.json()
            except Exception as exc:
                raise NiagaraBaskStreamError(f"/stream/health returned non-JSON: {exc}") from exc
        if response.status == 302:
            return None
        text = await response.text()
        raise NiagaraBaskStreamError(f"/stream/health HTTP {response.status}: {text[:300]}")

    async def login(self, username: str, password: str) -> dict[str, Any]:
        already = await self.health()
        if already:
            self._authenticated_user = str(already.get("authenticatedUser") or username)
            return already

        await self.http("GET", "/prelogin")
        user_step = await self.http(
            "POST",
            "/login",
            body=f"j_username={quote(username)}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body_text = await user_step.text()
        if user_step.status != 200 or "j_security_check" not in body_text:
            raise NiagaraBaskStreamError(
                "Niagara username step failed — verify user can log into station web."
            )

        client_nonce = base64.b64encode(os.urandom(16)).decode("ascii")
        client_first_bare = f"n={prep_username(username)},r={client_nonce}"
        client_first_message = f"n,,{client_first_bare}"
        first = await self.http(
            "POST",
            "/j_security_check/",
            body=f"action=sendClientFirstMessage&clientFirstMessage={client_first_message}",
            headers={"Content-Type": "application/x-niagara-login-support"},
        )
        if first.status != 200:
            raise NiagaraBaskStreamError(f"SCRAM first message failed: HTTP {first.status}")
        server_first = (await first.text()).strip()

        try:
            client_final_no_proof, proof_b64 = client_final_proof(
                username=username,
                client_nonce=client_nonce,
                server_first=server_first,
                password=password,
            )
        except ValueError as exc:
            raise NiagaraBaskStreamError(str(exc)) from exc

        final = await self.http(
            "POST",
            "/j_security_check/",
            body=f"action=sendClientFinalMessage&clientFinalMessage={client_final_no_proof},p={proof_b64}",
            headers={"Content-Type": "application/x-niagara-login-support"},
        )
        if final.status != 200:
            raise NiagaraBaskStreamError(f"SCRAM final message failed: HTTP {final.status}")

        await self.http("GET", "/j_security_check/")
        health = await self.health()
        if not health:
            raise NiagaraBaskStreamError(
                "/stream/health was not 200 after login (still 302). Check credentials."
            )
        self._authenticated_user = str(health.get("authenticatedUser") or username)
        return health

    def ws_url(self) -> str:
        parsed = urlparse(self.station_url)
        if parsed.scheme == "https":
            return f"wss://{parsed.netloc}/stream"
        if parsed.scheme == "http":
            return f"ws://{parsed.netloc}/stream"
        raise NiagaraBaskStreamError("station_url must start with http:// or https://")

    async def connect_ws(self) -> None:
        if not self._cookies.header():
            raise NiagaraBaskStreamError("No Niagara cookies — call login() first.")
        if self._ws is not None and not self._ws.closed:
            return
        session = await self._ensure_session()
        self._ws = await session.ws_connect(
            self.ws_url(),
            headers={"Cookie": self._cookies.header()},
            origin=f"{urlparse(self.station_url).scheme}://{urlparse(self.station_url).netloc}",
            ssl=self._ssl_context(),
        )

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def call(self, op: str, **fields: Any) -> dict[str, Any]:
        await self.connect_ws()
        assert self._ws is not None
        req_id = fields.pop("id", f"{op}-{uuid.uuid4().hex[:8]}")
        frame: dict[str, Any] = {"op": op, "id": req_id}
        frame.update(fields)
        await self._ws.send_bytes(msgpack.packb(frame, use_bin_type=True))
        while True:
            msg = await self._ws.receive(timeout=self.timeout.total)
            if msg.type != aiohttp.WSMsgType.BINARY:
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise NiagaraBaskStreamError(f"WebSocket closed during {op}")
                continue
            data = msgpack.unpackb(msg.data, raw=False)
            if data.get("id") != req_id:
                continue
            if data.get("error") or data.get("op") == "error":
                raise NiagaraBaskStreamError(json.dumps(data, indent=2, default=str))
            return data

    async def ping(self) -> dict[str, Any]:
        return await self.call("ping")

    async def capabilities(self) -> dict[str, Any]:
        return await self.call("capabilities")

    async def browse(self, base: str, *, depth: int = 1, metadata: str = "none") -> dict[str, Any]:
        return await self.call("browse", base=base, depth=depth, metadata=metadata)

    async def read(self, points: list[str]) -> dict[str, Any]:
        return await self.call("read", points=points)

    async def read_schedule(self, ord_value: str, *, at_ms: int | None = None) -> dict[str, Any]:
        frame: dict[str, Any] = {"ord": ord_value}
        if at_ms is not None:
            frame["at"] = at_ms
        return await self.call("read_schedule", **frame)
