#!/usr/bin/env python3
"""Remote building agent check-in via Tailscale/LAN REST API (no SSH).

Usage:
  python scripts/building_agent_checkin.py --base-url http://100.122.106.124
  python scripts/building_agent_checkin.py --base-url http://127.0.0.1:8765 --run-batch

Reads credentials from env (OFDD_AGENT_USER / OFDD_AGENT_PASSWORD) or --token.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _login(base: str, user: str, password: str) -> str:
    payload = json.dumps({"username": user, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    token = str(body.get("token") or "").strip()
    if not token:
        raise RuntimeError("login returned no token")
    return token


def _api_post(base: str, token: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Building agent check-in (API only)")
    parser.add_argument("--base-url", default=os.environ.get("OFDD_BRIDGE_BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=os.environ.get("OFDD_AGENT_TOKEN", "").strip())
    parser.add_argument("--user", default=os.environ.get("OFDD_AGENT_USER", "agent"))
    parser.add_argument("--password", default=os.environ.get("OFDD_AGENT_PASSWORD", ""))
    parser.add_argument("--site-id", default=os.environ.get("OFDD_SITE_ID", ""))
    parser.add_argument("--run-batch", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--window-minutes", type=int, default=60)
    parser.add_argument("--json", action="store_true", help="Print full JSON response")
    args = parser.parse_args(argv)

    token = args.token
    if not token:
        if not args.password:
            print("Set --token or OFDD_AGENT_PASSWORD", file=sys.stderr)
            return 2
        token = _login(args.base_url, args.user, args.password)

    body = {
        "run_fdd_batch": bool(args.run_batch),
        "write_memory": not args.no_memory,
        "window_minutes": args.window_minutes,
    }
    if args.site_id.strip():
        body["site_id"] = args.site_id.strip()

    result = _api_post(args.base_url, token, "/api/building-agent/checkin", body)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result.get("summary") or json.dumps(result)[:400])
        actions = result.get("actions") or []
        for act in actions[:6]:
            print(f"  - {act.get('kind')}: {act.get('detail')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
