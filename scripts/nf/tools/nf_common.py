#!/usr/bin/env python3
"""Shared helpers for the NF read-only tools in this folder (standard library only).

Nothing here knows a site, equipment name, point name, uuid or IP. Settings come from the
environment, optionally topped up from an env file you name on the command line (`--env FILE`)
or in `NF_ENV_FILE`. Never commit that file.

  NF_LAN_URL=https://<nf-host>        LAN path: the NF console port, or your TLS front door
  NF_CA_FILE=/path/to/lan-ca.crt      optional: a self-signed LAN cert to trust (added to the
                                      system CAs, so the portal path still verifies)
  NFURL=https://<installation-uuid>.normal-online.net      optional: the Normal Online portal path
  NF_CLIENT_ID=...  NF_CLIENT_SECRET=...                   an NF API key (console: Settings > API Keys)

Docs: https://docs.normal.dev/howto/auth/
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "open-fdd-nf-tools/1.0"
# Transient errors worth retrying. NF's Envoy front occasionally answers the token call with an
# empty-body 403 that succeeds moments later (seen on LAN and portal alike).
RETRY_CODES = (403, 429, 502, 503, 504)
RETRIES = 4
PATHS = {"lan": "NF_LAN_URL", "portal": "NFURL"}
# Markers every point carries; left out of printed tag labels.
GENERIC_MARKERS = {"point", "his", "cur", "writable"}


# ---------------------------------------------------------------------------- settings

def add_env_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env", metavar="FILE", default=os.environ.get("NF_ENV_FILE", ""),
                        help="KEY=VALUE env file with the NF_* settings (default: $NF_ENV_FILE; "
                             "values already in the environment win)")


def load_env_file(path: str | os.PathLike[str]) -> None:
    """Read KEY=VALUE lines into os.environ without overriding what is already set."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise SystemExit(f"env file not found: {file}")
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def load_settings(env_file: str = "") -> tuple[str, str]:
    """Apply the env file (if any) and return (client_id, client_secret) or exit with a hint."""
    if env_file:
        load_env_file(env_file)
    client_id = os.environ.get("NF_CLIENT_ID", "")
    client_secret = os.environ.get("NF_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit("NF requires an API key: set NF_CLIENT_ID and NF_CLIENT_SECRET "
                         "(environment or --env FILE).")
    return client_id, client_secret


@functools.cache
def ssl_context() -> ssl.SSLContext:
    """System CAs plus NF_CA_FILE (a self-signed LAN cert), so both paths verify."""
    ctx = ssl.create_default_context()
    ca = os.environ.get("NF_CA_FILE", "")
    if ca:
        ctx.load_verify_locations(cafile=str(Path(ca).expanduser()))
    return ctx


def base_url(path: str) -> str:
    """Base URL for 'lan' or 'portal' from the environment; there is no built-in default."""
    var = PATHS[path]
    url = os.environ.get(var, "").rstrip("/")
    if not url:
        raise SystemExit(f"set {var} (environment or --env FILE) for the {path} path")
    return url


# ---------------------------------------------------------------------------- HTTP

def request(url: str, body: dict | None = None, token: str | None = None) -> dict:
    """GET (no body) or POST (JSON body) with retries on transient errors; returns parsed JSON."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=120, context=ssl_context()) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            if exc.code in RETRY_CODES and attempt < RETRIES:
                wait = 2 ** attempt
                print(f"HTTP {exc.code} from {url.split('?')[0]}, retry {attempt}/"
                      f"{RETRIES - 1} in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise SystemExit(f"{url.split('?')[0]} failed HTTP {exc.code}: {detail}") from exc
    raise AssertionError("unreachable")


def bearer_token(base: str, client_id: str, client_secret: str) -> str:
    body = request(f"{base}/api/v1/auth/token", {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    })
    token = body.get("accessToken") or body.get("access_token")
    if not token:
        raise SystemExit(f"no accessToken in response keys: {sorted(body)}")
    return token


# ---------------------------------------------------------------------------- Haystack

def field(prop: str, text: str) -> dict:
    return {"field": {"property": prop, "text": text}}


def query(base: str, token: str, layer: str, *clauses: dict) -> list[dict]:
    """point/query on one layer, AND of the given field clauses (one marker per clause), all pages."""
    body: dict = {"pageSize": 500, "layer": layer}
    if clauses:
        body["structuredQuery"] = clauses[0] if len(clauses) == 1 else {"and": list(clauses)}
    out: list[dict] = []
    while True:
        page = request(f"{base}/api/v1/point/query", body, token)
        out.extend(page.get("points") or [])
        body["pageToken"] = page.get("nextPageToken") or ""
        if not body["pageToken"]:
            return out


def markers(rec: dict) -> list[str]:
    return [m for m in ((rec.get("attrs") or {}).get("markers") or "").split(",") if m]


def latest_number(point: dict) -> float | None:
    latest = point.get("latestValue") or {}
    value = latest.get("double", latest.get("real"))
    return None if value is None else float(value)


def split_csv(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


def console_utf8() -> None:
    """Units such as inH2O with a subscript crash a cp1252 console; replace instead of failing."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
