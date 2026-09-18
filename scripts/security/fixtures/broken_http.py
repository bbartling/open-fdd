"""Local HTTP fixtures for offline detector evaluation.

Modes deliberately break one control at a time so named detectors fire.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from openfdd_security.jwtutil import make_valid_token

SECRET = b"harness-isolated-test-key-32b!!"
CANARY_A = "CANARY_A_SYNTH"
CANARY_B = "CANARY_B_SYNTH"


def _json(handler: BaseHTTPRequestHandler, code: int, obj) -> None:
    raw = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def make_handler(mode: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            return

        def _auth(self) -> str | None:
            h = self.headers.get("Authorization") or ""
            if h.startswith("Bearer "):
                return h[7:].strip()
            return None

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            token = self._auth()

            if path == "/api/health":
                raw = json.dumps({"ok": True, "service": "fixture"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if mode == "cors_evil":
                    origin = self.headers.get("Origin")
                    if origin:
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Access-Control-Allow-Credentials", "true")
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/.well-known/security.txt":
                body = b"Contact: mailto:security@example.test\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/__oversized":
                # Exceed 1 MiB default when mode requests it
                if mode == "oversized":
                    payload = b"x" * (1 * 1024 * 1024 + 64)
                else:
                    payload = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if path == "/__redirect_off_origin":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9/sink")
                self.end_headers()
                return

            if path in ("/", "/auth"):
                self.send_response(200)
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'",
                )
                self.send_header("Content-Type", "text/html")
                body = b"<html><body>fixture</body></html>"
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # Protected routes
            if mode == "always_401" and path.startswith("/api/"):
                return _json(self, 401, {"ok": False, "error": "always"})

            if not token and path.startswith("/api/") and path not in (
                "/api/health",
                "/api/auth/login",
                "/api/auth/status",
            ):
                return _json(self, 401, {"ok": False, "error": "unauthorized"})

            # JWT validation for isolated secret modes
            if token and mode in (
                "healthy",
                "jwt_bypass_sig",
                "jwt_bypass_exp",
                "empty_200",
                "html_200",
                "foreign_canary",
                "viewer_mutation",
                "cors_evil",
                "wrong_identity",
            ):
                if mode == "jwt_bypass_sig":
                    pass  # accept any token
                elif mode == "jwt_bypass_exp":
                    pass  # accept expired too
                else:
                    # Require HS256 with SECRET for "valid" path — simplified:
                    # accept tokens that contain three segments; reject alg none / malformed
                    parts = token.split(".")
                    if len(parts) != 3 or parts[2] == "":
                        return _json(self, 401, {"ok": False})
                    # Reject obviously tampered (our harness flips first sig char)
                    # Decode payload for expiry when not bypass
                    try:
                        import base64

                        pad = "=" * (-len(parts[1]) % 4)
                        payload = json.loads(
                            base64.urlsafe_b64decode(parts[1] + pad)
                        )
                        import time

                        if mode != "jwt_bypass_exp" and int(payload.get("exp", 0)) < int(
                            time.time()
                        ):
                            return _json(self, 401, {"ok": False, "error": "expired"})
                        # Verify signature roughly
                        from openfdd_security.jwtutil import encode_jwt

                        # Rebuild expected for HS256
                        hdr_pad = "=" * (-len(parts[0]) % 4)
                        hdr = json.loads(base64.urlsafe_b64decode(parts[0] + hdr_pad))
                        if hdr.get("alg") == "none":
                            return _json(self, 401, {"ok": False})
                        expected = encode_jwt(payload, SECRET, header=hdr)
                        if expected != token and mode != "jwt_bypass_sig":
                            return _json(self, 401, {"ok": False, "error": "bad_sig"})
                    except Exception:
                        return _json(self, 401, {"ok": False})

            if path == "/api/auth/me":
                if mode == "wrong_identity":
                    return _json(
                        self, 200, {"sub": "other", "role": "admin", "tenant_ids": []}
                    )
                # Decode token payload for subject/role when present
                if token and token.count(".") == 2:
                    try:
                        import base64

                        parts = token.split(".")
                        pad = "=" * (-len(parts[1]) % 4)
                        payload = json.loads(
                            base64.urlsafe_b64decode(parts[1] + pad)
                        )
                        return _json(
                            self,
                            200,
                            {
                                "sub": payload.get("sub", "user"),
                                "role": payload.get("role", "operator"),
                                "tenant_ids": payload.get("tenant_ids") or [],
                            },
                        )
                    except Exception:
                        pass
                return _json(
                    self,
                    200,
                    {"sub": "operator_a", "role": "operator", "tenant_ids": ["tenant_a"]},
                )

            if path == "/api/edges":
                return _json(self, 200, {"edges": []})

            if path == "/api/fdd/equipment":
                bid = (qs.get("building_id") or [""])[0]
                # Infer caller tenant from token when possible
                caller_tids: list[str] = []
                if token and token.count(".") == 2:
                    try:
                        import base64

                        parts = token.split(".")
                        pad = "=" * (-len(parts[1]) % 4)
                        payload = json.loads(
                            base64.urlsafe_b64decode(parts[1] + pad)
                        )
                        caller_tids = list(payload.get("tenant_ids") or [])
                    except Exception:
                        caller_tids = []

                if mode == "empty_200" and bid == "BUILDING_B":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"[]")
                    return
                if mode == "html_200" and bid == "BUILDING_B":
                    body = b"<!doctype html><html><body>spa</body></html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if mode == "foreign_canary" and bid == "BUILDING_B":
                    return _json(
                        self,
                        200,
                        {"equipment": [{"id": "AHU_B", "canary": CANARY_B}]},
                    )
                if bid == "BUILDING_A":
                    if "tenant_b" in caller_tids and "tenant_a" not in caller_tids:
                        return _json(self, 403, {"ok": False, "error": "forbidden"})
                    return _json(
                        self,
                        200,
                        {"equipment": [{"id": "AHU_A", "canary": CANARY_A}]},
                    )
                if bid == "BUILDING_B":
                    if "tenant_a" in caller_tids and "tenant_b" not in caller_tids:
                        return _json(self, 403, {"ok": False, "error": "forbidden"})
                    if not caller_tids:
                        # admin / unset — allow own-style for simplicity in healthy
                        return _json(
                            self,
                            200,
                            {"equipment": [{"id": "AHU_B", "canary": CANARY_B}]},
                        )
                    return _json(
                        self,
                        200,
                        {"equipment": [{"id": "AHU_B", "canary": CANARY_B}]},
                    )
                return _json(self, 404, {"ok": False})

            if path == "/api/admin/users":
                return _json(self, 403, {"ok": False})

            if path.startswith("/api/"):
                return _json(self, 401, {"ok": False})

            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode() or "{}")
            except Exception:
                body = {}

            if path == "/api/auth/login":
                user = body.get("username")
                pw = body.get("password")
                if mode == "wrong_identity":
                    tok = make_valid_token(SECRET, sub="wrong", role="viewer")
                    return _json(self, 200, {"token": tok})
                if user and pw:
                    role = "operator"
                    tids: list[str] = []
                    if user == "admin":
                        role = "admin"
                    elif user == "viewer":
                        role = "viewer"
                        tids = ["tenant_a"]
                    elif user in ("ops_a", "ops_b", "acme-ops", "b100-ops"):
                        role = "operator"
                        tids = (
                            ["tenant_b"]
                            if user in ("ops_b", "b100-ops")
                            else ["tenant_a"]
                        )
                    tok = make_valid_token(
                        SECRET, sub=user, role=role, tenant_ids=tids
                    )
                    return _json(self, 200, {"token": tok})
                return _json(self, 401, {"ok": False, "error": "invalid"})

            if path == "/api/auth/agent-token":
                if mode == "viewer_mutation":
                    return _json(self, 200, {"token": make_valid_token(SECRET)})
                return _json(self, 403, {"ok": False})

            return _json(self, 404, {"ok": False})

        def do_OPTIONS(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin") or ""
            self.send_response(204)
            if mode == "cors_evil" and origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()

    return Handler


class FixtureServer:
    def __init__(self, mode: str = "healthy", host: str = "127.0.0.1", port: int = 0):
        self.mode = mode
        handler = make_handler(mode)
        self.httpd = HTTPServer((host, port), handler)
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://{host}:{self.port}"
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
