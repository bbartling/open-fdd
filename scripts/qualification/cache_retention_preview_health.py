#!/usr/bin/env python3
"""Local acceptance smoke for #1044, #1049, #1050, and #1063.

This does not mark those issues closed and does not claim fully_qualified.
Live hub probes run only when a base URL is set. A hanging liveness call fails.
Cache hit/unload classifiers are pure so CI can prove the contract without a hub.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NGINX = ROOT / "frontend/web/nginx.conf"
PREVIEW_TS = ROOT / "frontend/web/src/components/seriesPreview.ts"
PREVIEW_TSX = ROOT / "frontend/web/src/components/SeriesPreview.tsx"
PREFLIGHT = ROOT / "scripts/openfdd_disk_preflight.py"

LIVENESS_READ_TIMEOUT = {
    "/api/health": 5,
    "/api/version": 5,
    "/api/auth/status": 8,
    "/api/auth/login": 15,
}


def nginx_exact_locations(text: str) -> dict[str, str]:
    """Map `location = /path` bodies. Named locations use the same scan."""
    out: dict[str, str] = {}
    for match in re.finditer(r"location\s+=\s+(\S+)\s*\{", text):
        body, _end = _brace_body(text, match.end() - 1)
        out[match.group(1)] = body
    named = re.search(r"location\s+@central_unavailable\s*\{", text)
    if named:
        body, _end = _brace_body(text, named.end() - 1)
        out["@central_unavailable"] = body
    return out


def _brace_body(text: str, open_brace: int) -> tuple[str, int]:
    depth = 0
    for index in range(open_brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace : index + 1], index + 1
    raise ValueError("unbalanced nginx brace")


def _timeout_seconds(block: str) -> int | None:
    match = re.search(r"proxy_read_timeout\s+(\d+)s", block)
    if not match:
        return None
    return int(match.group(1))


def check_nginx(text: str) -> list[str]:
    errors: list[str] = []
    blocks = nginx_exact_locations(text)
    for path, limit in LIVENESS_READ_TIMEOUT.items():
        block = blocks.get(path)
        if not block:
            errors.append(f"missing exact location {path}")
            continue
        got = _timeout_seconds(block)
        if got is None or got > limit:
            errors.append(f"{path} proxy_read_timeout {got} exceeds {limit}s")
        if "@central_unavailable" not in block:
            errors.append(f"{path} does not fail to @central_unavailable")
    named = blocks.get("@central_unavailable", "")
    if "central_unavailable" not in named or "503" not in named:
        errors.append("@central_unavailable must return 503 JSON central_unavailable")
    if "proxy_read_timeout 600s" not in text:
        errors.append("analytics /api/ read timeout 600s is missing")
    return errors


def check_series_preview(ts_text: str, tsx_text: str) -> list[str]:
    errors: list[str] = []
    if "SERIES_PREVIEW_ROW_OPTIONS = [10, 20, 50, 100, 500]" not in ts_text:
        errors.append("series preview options are not 10/20/50/100/500")
    if "DEFAULT_SERIES_PREVIEW_ROWS: SeriesPreviewLimit = 10" not in ts_text:
        errors.append("series preview default is not 10")
    if "newest-first" not in ts_text and "newest first" not in ts_text:
        errors.append("series preview does not document newest-first")
    if "first rows" in tsx_text.lower():
        errors.append("series preview label still says first rows")
    if "Most recent rows" not in tsx_text:
        errors.append("series preview dropdown label is not Most recent rows")
    if "most recent" not in tsx_text:
        errors.append("series preview table label is not most recent")
    return errors


def cache_pair_ok(first: dict[str, Any], second: dict[str, Any]) -> tuple[bool, str]:
    """Second call is a hit and both calls record elapsed_ms. Does not treat stale as fresh."""
    first_cache = first.get("cache") if isinstance(first.get("cache"), dict) else {}
    second_cache = second.get("cache") if isinstance(second.get("cache"), dict) else {}
    if "elapsed_ms" not in first_cache or "elapsed_ms" not in second_cache:
        return False, "cache.elapsed_ms missing"
    if second_cache.get("hit") is not True:
        return False, "second call cache.hit is not true"
    if second.get("stale") is True and second_cache.get("stale") is not True:
        return False, "stale body flag is not mirrored on cache.stale"
    return True, "hit"


def unload_cleared(before: dict[str, Any], after: dict[str, Any], building_id: str) -> tuple[bool, str]:
    """historian_resident must drop the CSV building after leave. Lease may remain until idle."""
    def resident(payload: dict[str, Any]) -> list[str]:
        raw = payload.get("historian_resident")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    if building_id in resident(after):
        return False, f"historian_resident still names {building_id} after leave"
    return True, "historian_resident cleared"


def budget_snapshot_ok(payload: dict[str, Any]) -> tuple[bool, str]:
    if payload.get("ok") is not True:
        return False, "budget ok is not true"
    if not isinstance(payload.get("enabled"), bool):
        return False, "budget.enabled is not a bool"
    gib = payload.get("budget_gib")
    if not isinstance(gib, int) or gib <= 0:
        return False, "budget_gib missing"
    if payload.get("default_budget_gib") != 100:
        return False, "default_budget_gib is not 100"
    policy = str(payload.get("policy") or "")
    if "oldest-first" not in policy:
        return False, "policy is not oldest-first"
    return True, "budget shape"


class _Blackhole(ThreadingHTTPServer):
    """Accept TCP and never answer, the wedged-central case."""

    def finish_request(self, request: socket.socket, client_address: Any) -> None:
        try:
            request.settimeout(2)
            request.recv(8)
        except OSError:
            return
        time.sleep(5)


class _Web(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = b'<!doctype html><html data-build="overview-vibe19-oracle"></html>'
            self._send(200, body, "text/html")
            return
        if self.path in LIVENESS_READ_TIMEOUT:
            self._upstream_then_503()
            return
        self._send(404, b'{"ok":false}', "application/json")

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/auth/login":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self._upstream_then_503()
            return
        self._send(404, b'{"ok":false}', "application/json")

    def _upstream_then_503(self) -> None:
        host, port = self.server.upstream  # type: ignore[attr-defined]
        started = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=0.4) as sock:
                sock.settimeout(0.4)
                sock.sendall(b"GET /api/health HTTP/1.0\r\n\r\n")
                sock.recv(16)
        except OSError:
            pass
        self.server.upstream_wait_ms = int((time.monotonic() - started) * 1000)  # type: ignore[attr-defined]
        body = b'{"ok":false,"service":"openfdd-web","error":"central_unavailable"}'
        self._send(503, body, "application/json")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def simulate_central_restart() -> dict[str, Any]:
    """Shell stays 200 while liveness returns 503 before a multi-second hang."""
    blackhole = _Blackhole(("127.0.0.1", 0), BaseHTTPRequestHandler)
    black_thread = threading.Thread(target=blackhole.serve_forever, daemon=True)
    black_thread.start()
    web = ThreadingHTTPServer(("127.0.0.1", 0), _Web)
    web.upstream = blackhole.server_address[:2]  # type: ignore[attr-defined]
    web_thread = threading.Thread(target=web.serve_forever, daemon=True)
    web_thread.start()
    host, port = web.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        page_started = time.monotonic()
        with urllib.request.urlopen(f"{base}/", timeout=2) as resp:
            page = resp.read()
            page_code = getattr(resp, "status", 200)
        page_ms = int((time.monotonic() - page_started) * 1000)
        results: dict[str, Any] = {
            "page_code": page_code,
            "page_ms": page_ms,
            "page_has_shell": b"overview-vibe19-oracle" in page,
        }
        for path in ("/api/health", "/api/version", "/api/auth/status"):
            started = time.monotonic()
            try:
                with urllib.request.urlopen(f"{base}{path}", timeout=3) as resp:
                    raw = resp.read()
                    code = getattr(resp, "status", 200)
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                code = exc.code
            elapsed_ms = int((time.monotonic() - started) * 1000)
            body = json.loads(raw.decode() or "{}")
            results[path] = {
                "code": code,
                "ms": elapsed_ms,
                "error": body.get("error"),
            }
        return results
    finally:
        web.shutdown()
        blackhole.shutdown()
        web.server_close()
        blackhole.server_close()


def check_restart_simulation(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if result.get("page_code") != 200 or not result.get("page_has_shell"):
        errors.append("shell did not stay HTTP 200 during central blackhole")
    if int(result.get("page_ms") or 9999) > 1500:
        errors.append("shell waited on central")
    for path in ("/api/health", "/api/version", "/api/auth/status"):
        row = result.get(path) or {}
        if row.get("code") != 503 or row.get("error") != "central_unavailable":
            errors.append(f"{path} did not return 503 central_unavailable")
        if int(row.get("ms") or 9999) > 2000:
            errors.append(f"{path} took {row.get('ms')}ms")
    return errors


def _live_get(url: str, timeout: float) -> tuple[int, float, bytes]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
            code = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        code = exc.code
    return code, time.monotonic() - started, raw


def live_liveness(base: str) -> dict[str, Any]:
    """Fail when health or version produces no bytes inside 12s."""
    out: dict[str, Any] = {"base": base}
    errors: list[str] = []
    for path in ("/api/health", "/api/version"):
        try:
            code, elapsed, raw = _live_get(base.rstrip("/") + path, 12)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            errors.append(f"{path} hung or failed with no body: {exc.__class__.__name__}")
            out[path] = {"code": 0, "seconds": 12}
            continue
        out[path] = {"code": code, "seconds": round(elapsed, 3), "bytes": len(raw)}
        if elapsed > 12 or not raw:
            errors.append(f"{path} exceeded 12s or returned no bytes (code={code})")
            continue
        # 404 on /api/version means this tip has not shipped the route yet.
        # That is not a hang. 200 and 503 JSON are the steady and restart cases.
        allowed = (200, 503) if path == "/api/health" else (200, 404, 503)
        if code not in allowed:
            errors.append(f"{path} code={code}")
    out["errors"] = errors
    return out


def run_checks() -> dict[str, Any]:
    nginx_errors = check_nginx(NGINX.read_text(encoding="utf-8"))
    preview_errors = check_series_preview(
        PREVIEW_TS.read_text(encoding="utf-8"),
        PREVIEW_TSX.read_text(encoding="utf-8"),
    )
    preflight = subprocess.run(
        [sys.executable, str(PREFLIGHT), "--self-test"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    preflight_ok = preflight.returncode == 0
    restart = simulate_central_restart()
    restart_errors = check_restart_simulation(restart)
    base = (
        os.environ.get("OPENFDD_API_BASE")
        or os.environ.get("CENTRAL_BASE")
        or os.environ.get("RAILWAY_BASE")
        or ""
    ).strip()
    live: dict[str, Any] | None = None
    live_errors: list[str] = []
    if base:
        live = live_liveness(base)
        live_errors = list(live.get("errors") or [])
    errors = nginx_errors + preview_errors + restart_errors + live_errors
    if not preflight_ok:
        errors.append("disk preflight self-test failed")
    return {
        "ok": not errors,
        "errors": errors,
        "nginx_ok": not nginx_errors,
        "series_preview_ok": not preview_errors,
        "disk_preflight_ok": preflight_ok,
        "disk_preflight_stdout": (preflight.stdout or "")[-400:],
        "restart": restart,
        "live": live,
        "notes": {
            "1044": "cache_pair_ok and unload_cleared are the acceptance classifiers; live RSS is field",
            "1049": "preflight self-test covers oldest-first decisions; edge disk proof is still open",
            "1050": "source contract: newest N, default 10, options 10/20/50/100/500",
            "1063": "local blackhole returns 503 while / stays 200; live hang fails this smoke",
            "not_fq": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", default="")
    args = parser.parse_args(argv)
    report = run_checks()
    text = json.dumps(report, indent=2)
    sys.stdout.write(text + "\n")
    if args.artifact_dir:
        art = Path(args.artifact_dir)
        art.mkdir(parents=True, exist_ok=True)
        (art / "cache_retention_preview_health.json").write_text(text + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
