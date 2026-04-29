"""
Headless BACnet scrape loop (DIY BACnet server over JSON-RPC).

Mirrors afdd-stack's ``run_bacnet_scrape`` entrypoint style for operators who want
cron/systemd without the full FastAPI bridge UI.

Modes:

* **local** (default): uses ``IngestService`` + on-disk Feather/model (same as bridge).
* **bridge**: POST ``/ingest/bacnet`` to an existing bridge (remote orchestration).

Examples::

    # One-shot against local data dir (run from open-fdd repo root)
    OFDD_BACNET_SITE_ID=<uuid> OFDD_BACNET_SERVER_URL=http://localhost:8080 \\
        python -m open_fdd.platform.drivers.headless_bacnet once

    # Loop every 300s, hitting bridge on another host
    python -m open_fdd.platform.drivers.headless_bacnet loop --mode bridge \\
        --bridge-url http://127.0.0.1:8765 --interval 300
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _post_json(url: str, body: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise SystemExit(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Request failed {url}: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {"raw": out}
    except json.JSONDecodeError:
        return {"ok": False, "text": raw[:2000]}


def _run_local_once(
    *,
    site_id: str,
    server_url: str,
    api_key: str,
) -> dict[str, Any]:
    from open_fdd.desktop.services.ingest_service import IngestService

    svc = IngestService()
    return svc.ingest_bacnet(site_id=site_id, server_url=server_url, api_key=api_key)


def run_bridge_once(
    *,
    bridge: str,
    site_id: str,
    server_url: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    raw = str(bridge or "").strip()
    if not raw:
        return {"ok": False, "success": False, "error": "empty bridge URL"}
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return {
            "ok": False,
            "success": False,
            "error": f"bridge URL must use http or https, got scheme={parsed.scheme!r}",
        }
    bridge_base = raw.rstrip("/")
    body: dict[str, Any] = {"site_id": site_id}
    if server_url:
        body["server_url"] = server_url
    if api_key:
        body["api_key"] = api_key
    return _post_json(f"{bridge_base}/ingest/bacnet", body)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Headless BACnet ingest (local IngestService or bridge HTTP).")
    sub = p.add_subparsers(dest="cmd", required=True)

    once = sub.add_parser("once", help="Run a single BACnet ingest.")
    loop = sub.add_parser("loop", help="Run ingest every --interval seconds (SIGINT to stop).")

    for sp in (once, loop):
        sp.add_argument(
            "--mode",
            choices=("local", "bridge"),
            default=os.getenv("OFDD_HEADLESS_BACNET_MODE", "local"),
            help="local=IngestService; bridge=POST /ingest/bacnet",
        )
        sp.add_argument(
            "--bridge-url",
            default=os.getenv("OFDD_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/"),
            help="Bridge base URL (bridge mode only).",
        )
        sp.add_argument(
            "--site-id",
            default=os.getenv("OFDD_BACNET_SITE_ID", "").strip(),
            help="Site UUID (or set OFDD_BACNET_SITE_ID).",
        )
        sp.add_argument(
            "--server-url",
            default=os.getenv("OFDD_BACNET_SERVER_URL", "").strip(),
            help="DIY BACnet server base URL (local mode; optional in bridge mode if already configured).",
        )
        sp.add_argument(
            "--api-key",
            default=os.getenv("OFDD_BACNET_SERVER_API_KEY", "").strip(),
            help="Bearer token for DIY server (optional).",
        )

    def _interval_default() -> int:
        raw = os.getenv("OFDD_BACNET_HEADLESS_INTERVAL", "300")
        try:
            v = int(str(raw).strip(), 10)
            return v if v >= 1 else 300
        except (TypeError, ValueError):
            return 300

    loop.add_argument(
        "--interval",
        type=int,
        default=_interval_default(),
        help="Seconds between runs (default 300).",
    )

    args = p.parse_args(argv)
    site_id = str(args.site_id or "").strip()
    if not site_id:
        print("error: --site-id or OFDD_BACNET_SITE_ID is required", file=sys.stderr)
        raise SystemExit(2)

    def run_one() -> dict[str, Any]:
        if args.mode == "bridge":
            return run_bridge_once(
                bridge=args.bridge_url,
                site_id=site_id,
                server_url=str(args.server_url).strip() or None,
                api_key=str(args.api_key).strip() or None,
            )
        server = str(args.server_url or "").strip()
        if not server:
            print("error: --server-url or OFDD_BACNET_SERVER_URL required for local mode", file=sys.stderr)
            raise SystemExit(2)
        return _run_local_once(site_id=site_id, server_url=server, api_key=str(args.api_key or ""))

    if args.cmd == "once":
        out = run_one()
        print(json.dumps(out, indent=2, default=str))
        if not out.get("success", True):
            raise SystemExit(1)
        return

    interval = max(5, int(args.interval))
    print(f"[headless-bacnet] loop mode={args.mode} interval={interval}s site_id={site_id}", flush=True)
    while True:
        try:
            out = run_one()
            ok = out.get("success", True)
            print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), json.dumps(out, default=str), flush=True)
            if not ok:
                print("[headless-bacnet] ingest reported success=false", file=sys.stderr)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"[headless-bacnet] error: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    main()
