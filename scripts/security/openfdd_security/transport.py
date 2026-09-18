"""Safe HTTP transport: no redirects, no env proxies, bounded bodies."""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


class TransportError(RuntimeError):
    """Network / parse / budget fault (maps to ERROR, not authz PASS)."""


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_s: float
    url: str
    redirected: bool = False
    location: str | None = None

    def text(self, max_chars: int = 4096) -> str:
        return self.body[:max_chars].decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def header(self, name: str) -> str | None:
        lower = {k.lower(): v for k, v in self.headers.items()}
        return lower.get(name.lower())


@dataclass
class Budget:
    max_requests: int = 200
    timeout_s: float = 10.0
    deadline_s: float = 300.0
    rate_rps: float = 1.0
    max_body_bytes: int = 1 * 1024 * 1024
    started_at: float = field(default_factory=time.monotonic)
    request_count: int = 0
    cleanup_reserved: int = 10
    _last_request_at: float = 0.0

    def remaining(self) -> int:
        return max(0, self.max_requests - self.request_count)

    def check_deadline(self) -> None:
        if time.monotonic() - self.started_at > self.deadline_s:
            raise TransportError("run deadline exceeded")

    def consume(self, *, cleanup: bool = False) -> None:
        self.check_deadline()
        if not cleanup and self.remaining() <= self.cleanup_reserved:
            if self.request_count >= self.max_requests - self.cleanup_reserved:
                raise TransportError("request budget exhausted (cleanup reserved)")
        if self.request_count >= self.max_requests:
            raise TransportError("request budget exhausted")
        # Rate limit
        if self.rate_rps > 0 and self._last_request_at:
            min_gap = 1.0 / self.rate_rps
            wait = min_gap - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        self.request_count += 1
        self._last_request_at = time.monotonic()


class SafeHttpClient:
    """Minimal client: exact origin, no automatic redirects, no env proxies."""

    def __init__(
        self,
        base_url: str,
        *,
        budget: Budget,
        tls_verify: bool = True,
        ca_file: str | None = None,
        allow_credentials_on_redirect: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.budget = budget
        self.tls_verify = tls_verify
        self.ca_file = ca_file
        self.allow_credentials_on_redirect = allow_credentials_on_redirect
        self.origin = self.base_url
        self.redirect_sink_hits = 0
        parsed = urlparse(self.base_url)
        self._scheme = parsed.scheme
        self._host = parsed.hostname or ""
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._scheme != "https":
            return None
        if not self.tls_verify:
            raise TransportError("--insecure is not supported; set tls.ca_file")
        ctx = ssl.create_default_context(cafile=self.ca_file)
        return ctx

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
        json_body: Any = None,
        token: str | None = None,
        cleanup: bool = False,
        expect_redirect: bool = False,
    ) -> Response:
        self.budget.consume(cleanup=cleanup)
        hdrs = {k: v for k, v in (headers or {}).items()}
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        raw: bytes | None
        if json_body is not None:
            raw = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = body

        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        t0 = time.monotonic()
        try:
            if self._scheme == "https":
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    self._host,
                    self._port,
                    timeout=self.budget.timeout_s,
                    context=self._ssl_context(),
                )
            else:
                conn = http.client.HTTPConnection(
                    self._host, self._port, timeout=self.budget.timeout_s
                )
            conn.request(method.upper(), path, body=raw, headers=hdrs)
            resp = conn.getresponse()
            # Do not follow redirects automatically
            loc = resp.getheader("Location")
            status = resp.status
            # Read with body cap
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.budget.max_body_bytes:
                    conn.close()
                    raise TransportError("response body exceeds max_body_bytes")
                chunks.append(chunk)
            body_bytes = b"".join(chunks)
            header_map = {k: v for k, v in resp.getheaders()}
            conn.close()
        except (OSError, socket.timeout, http.client.HTTPException) as exc:
            raise TransportError(f"transport fault: {type(exc).__name__}") from exc

        elapsed = time.monotonic() - t0
        redirected = status in (301, 302, 303, 307, 308)
        if redirected and not expect_redirect:
            # Never forward credentials off-origin
            if loc:
                loc_parsed = urlparse(loc if "://" in loc else f"{self.base_url}{loc}")
                same = (
                    loc_parsed.scheme == self._scheme
                    and loc_parsed.hostname == self._host
                    and (loc_parsed.port or self._port) == self._port
                )
                if not same:
                    self.redirect_sink_hits += 0  # we did not follow
                    if token and not self.allow_credentials_on_redirect:
                        # Evidence: credentials were NOT forwarded
                        pass
            # Unexpected redirect is not denial PASS — caller must classify ERROR
        return Response(
            status=status,
            headers=header_map,
            body=body_bytes,
            elapsed_s=elapsed,
            url=url,
            redirected=redirected,
            location=loc,
        )
