#!/usr/bin/env python3
"""Prove a disposable loopback stack is the product central + Timescale SPA.

Refuses non-loopback bases (Railway and any other remote host). Requires the
SPA shell, a healthy Timescale-backed central, auth on, and starter seed off.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise RuntimeError(f"unexpected redirect {code}")


def loopback_problem(base: str) -> str | None:
    host = urllib.parse.urlparse(base).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        shown = host or "(missing)"
        return f"base URL host must be loopback (got {shown})"
    return None


def problems(spa_status: int, spa_body: bytes, health: dict[str, Any], auth: dict[str, Any]) -> list[str]:
    found: list[str] = []
    if spa_status != 200:
        found.append(f"SPA HTTP {spa_status}")
    if b'id="root"' not in spa_body and b"id='root'" not in spa_body:
        found.append("SPA body has no root element")
    if health.get("ok") is not True:
        found.append("central ok is not true")
    if health.get("service") != "openfdd-central":
        found.append(f"central service is {health.get('service')!r}")
    if health.get("timescale_ok") is not True:
        found.append("timescale_ok is not true")
    if health.get("historian") != "timescale":
        found.append(f"historian is {health.get('historian')!r}")
    if health.get("fdd_engine") != "postgres-sql":
        found.append(f"fdd_engine is {health.get('fdd_engine')!r}")
    if health.get("dual_write") is not False:
        found.append("dual_write is not false")
    if health.get("starter_seed") != "disabled":
        found.append(f"starter_seed is {health.get('starter_seed')!r}")
    if auth.get("ok") is not True:
        found.append("auth status ok is not true")
    if auth.get("auth_required") is not True:
        found.append("auth_required is not true")
    return found


def _get(url: str, timeout: float) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), response.read(400_000)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(400_000)


def _json_body(kind: str, body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{kind} body is not JSON ({exc})") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{kind} body is not a JSON object")
    return parsed


def check_base(base: str, timeout: float) -> tuple[int, list[str]]:
    problem = loopback_problem(base)
    if problem:
        return 1, [f"FAIL: {problem}"]
    root = base.rstrip("/")
    try:
        spa_status, spa_body = _get(f"{root}/", timeout)
        health_status, health_body = _get(f"{root}/api/health", timeout)
        auth_status, auth_body = _get(f"{root}/api/auth/status", timeout)
    except Exception as exc:
        return 1, [f"FAIL: {exc}"]
    if health_status != 200:
        return 1, [f"FAIL: /api/health HTTP {health_status}"]
    if auth_status != 200:
        return 1, [f"FAIL: /api/auth/status HTTP {auth_status}"]
    try:
        health = _json_body("health", health_body)
        auth = _json_body("auth", auth_body)
    except RuntimeError as exc:
        return 1, [f"FAIL: {exc}"]
    found = problems(spa_status, spa_body, health, auth)
    if found:
        return 1, [f"FAIL: {item}" for item in found]
    return 0, [
        "stack-health:"
        " spa=200"
        " service=openfdd-central"
        " timescale_ok=true"
        " historian=timescale"
        " fdd_engine=postgres-sql"
        " dual_write=false"
        " starter_seed=disabled"
        " auth_required=true"
    ]


def _healthy() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "openfdd-central",
        "timescale_ok": True,
        "historian": "timescale",
        "fdd_engine": "postgres-sql",
        "dual_write": False,
        "starter_seed": "disabled",
    }


def self_test() -> int:
    failures: list[str] = []
    good = problems(200, b'<div id="root"></div>', _healthy(), {"ok": True, "auth_required": True})
    if good:
        failures.append(f"healthy proof was rejected: {good}")
    if loopback_problem("http://127.0.0.1:3000") is not None:
        failures.append("loopback base was rejected")
    if loopback_problem("http://openfdd.railway.app") is None:
        failures.append("Railway host was accepted")
    if loopback_problem("https://example.com") is None:
        failures.append("remote host was accepted")
    seeded = _healthy()
    seeded["starter_seed"] = "seeded"
    if not problems(200, b'<div id="root"></div>', seeded, {"ok": True, "auth_required": True}):
        failures.append("seeded starter was accepted")
    offline = _healthy()
    offline["timescale_ok"] = False
    if not problems(200, b'<div id="root"></div>', offline, {"ok": True, "auth_required": True}):
        failures.append("timescale_ok false was accepted")
    open_auth = problems(200, b'<div id="root"></div>', _healthy(), {"ok": True, "auth_required": False})
    if not open_auth:
        failures.append("auth_required false was accepted")
    if not problems(500, b'<div id="root"></div>', _healthy(), {"ok": True, "auth_required": True}):
        failures.append("SPA HTTP 500 was accepted")
    if failures:
        print("browser_stack_health --self-test FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("browser_stack_health --self-test OK (positive=1 negative=6)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.base:
        print("FAIL: --base is required", file=sys.stderr)
        return 1
    code, lines = check_base(args.base, args.timeout)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
