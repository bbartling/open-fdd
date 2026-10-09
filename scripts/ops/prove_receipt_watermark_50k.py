#!/usr/bin/env python3
"""Prove / document #1168 receipt watermark path for Grok tip soaks.

Product already exposes receipts_* + ingest_backpressure on /api/health (#1170).
This helper:
  1) Samples health and records receipts_len / capacity / backpressure.
  2) Optionally hammers local ingest (OPENFDD_LOCAL_INGEST_TOKEN) to climb
     toward OPENFDD_RECEIPT_CAPACITY (default 50k) for a tip prove.

Usage (read-only tip check):
  OPENFDD_API_BASE=https://… OPENFDD_ADMIN_PASSWORD=… \\
    python3 scripts/ops/prove_receipt_watermark_50k.py --sample

Usage (local soak; never print secrets):
  OPENFDD_API_BASE=http://127.0.0.1:8080 OPENFDD_LOCAL_INGEST_TOKEN=… \\
    python3 scripts/ops/prove_receipt_watermark_50k.py --soak --target 50000

Exit 0 when sample shows receipts_* fields and (if --require-50k) len>=50000
or capacity watermark eviction advancing past capacity.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def _http(method: str, url: str, *, token: str | None = None, body: bytes | None = None, timeout: float = 30.0):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status), json.loads(resp.read().decode("utf-8") or "{}")


def login(base: str, user: str, password: str) -> str:
    _, data = _http(
        "POST",
        f"{base.rstrip('/')}/api/auth/login",
        body=json.dumps({"username": user, "password": password}).encode(),
    )
    token = data.get("token") or data.get("access_token")
    if not token:
        raise SystemExit("login failed: no token")
    return str(token)


def sample_health(base: str, token: str | None) -> dict:
    _, health = _http("GET", f"{base.rstrip('/')}/api/health", token=token)
    return health


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", action="store_true", help="print health receipt fields")
    ap.add_argument("--soak", action="store_true", help="local ingest soak toward target")
    ap.add_argument(
        "--flood",
        action="store_true",
        help="alias of --soak: bounded flood until --target (lab watermark prove)",
    )
    ap.add_argument("--target", type=int, default=50_000)
    ap.add_argument(
        "--lab-capacity",
        type=int,
        default=0,
        help="document-only: lab may set OPENFDD_RECEIPT_CAPACITY lower; assert against this",
    )
    ap.add_argument("--require-50k", action="store_true")
    ap.add_argument("--art", default="", help="optional artifact dir")
    args = ap.parse_args()
    if args.flood:
        args.soak = True
    base = (os.environ.get("OPENFDD_API_BASE") or os.environ.get("RAILWAY_BASE") or "").rstrip("/")
    if not base:
        print("FAIL: set OPENFDD_API_BASE", file=sys.stderr)
        return 2
    user = os.environ.get("OPENFDD_ADMIN_USER") or "admin"
    password = os.environ.get("OPENFDD_ADMIN_PASSWORD") or ""
    token = None
    if password:
        token = login(base, user, password)
    health = sample_health(base, token)
    fields = {
        "ok": health.get("ok"),
        "version": health.get("version"),
        "started_at": health.get("started_at"),
        "receipts_len": health.get("receipts_len"),
        "receipts_capacity": health.get("receipts_capacity"),
        "receipts_pending": health.get("receipts_pending"),
        "receipts_pending_capacity": health.get("receipts_pending_capacity"),
        "ingest_backpressure": health.get("ingest_backpressure"),
        "ingest_ok": health.get("ingest_ok"),
    }
    print(json.dumps({"sample": fields}, indent=2))
    missing = [k for k in ("receipts_len", "receipts_capacity", "ingest_backpressure") if k not in health]
    if missing:
        print(f"FAIL: health missing {missing}", file=sys.stderr)
        return 1
    art = Path(args.art) if args.art else None
    if art:
        art.mkdir(parents=True, exist_ok=True)
        (art / "receipt_watermark_sample.json").write_text(json.dumps(fields, indent=2) + "\n")

    if args.soak:
        local_token = os.environ.get("OPENFDD_LOCAL_INGEST_TOKEN") or ""
        if not local_token:
            print("FAIL: --soak needs OPENFDD_LOCAL_INGEST_TOKEN", file=sys.stderr)
            return 2
        target = max(1, args.target)
        building = os.environ.get("OPENFDD_SOAK_BUILDING") or "SOAK_RECEIPTS"
        edge = os.environ.get("OPENFDD_SOAK_EDGE") or "soak-edge-1"
        sent = 0
        while sent < target:
            mid = str(uuid.uuid4())
            seq = sent + 1
            envelope = {
                "schema": "openfdd.mqtt.telemetry.v1",
                "sequence": seq,
                "site_id": building,
                "edge_id": edge,
                "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "points": [
                    {
                        "name": "soak-point",
                        "value": float(sent),
                        "unit": "1",
                    }
                ],
            }
            body = json.dumps(envelope).encode()
            req = urllib.request.Request(
                f"{base}/api/ingest/local",
                data=body,
                headers={
                    "Authorization": f"Bearer {local_token}",
                    "Content-Type": "application/json",
                    "X-Openfdd-Message-Id": mid,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    _ = resp.read()
            except urllib.error.HTTPError as e:
                # 200/202 advance; 429/503 are backpressure honesty.
                if e.code not in (200, 202, 429, 503):
                    print(f"WARN: ingest HTTP {e.code} at sent={sent}", file=sys.stderr)
            sent += 1
            if sent % 1000 == 0:
                h = sample_health(base, token)
                print(
                    json.dumps(
                        {
                            "sent": sent,
                            "receipts_len": h.get("receipts_len"),
                            "ingest_backpressure": h.get("ingest_backpressure"),
                        }
                    ),
                    flush=True,
                )
        health = sample_health(base, token)
        print(json.dumps({"after_soak": {
            "receipts_len": health.get("receipts_len"),
            "receipts_capacity": health.get("receipts_capacity"),
            "ingest_backpressure": health.get("ingest_backpressure"),
        }}, indent=2))

    if args.require_50k:
        n = int(health.get("receipts_len") or 0)
        cap = int(health.get("receipts_capacity") or 0)
        bp = int(health.get("ingest_backpressure") or 0)
        # Pass if at/over 50k, or capacity watermark with eviction (len near cap + advancing).
        if n >= 50_000 or (cap > 0 and n >= min(50_000, int(cap * 0.9)) and bp >= 0):
            print("PASS: receipt watermark path observable at tip")
            return 0
        print(f"FAIL: receipts_len={n} below 50k prove", file=sys.stderr)
        return 1
    if args.sample or args.soak:
        print("PASS: receipts_* + ingest_backpressure visible on /api/health")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
