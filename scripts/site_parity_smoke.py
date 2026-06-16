#!/usr/bin/env python3
"""Cross-site parity smoke — bensserver vs edge (UI bundle + API revision).

Compares health, stack metadata, and dashboard JS bundle hash between two Open-FDD
sites. Intended to run before/after deploy and during paired smoke tests.

  python3 scripts/site_parity_smoke.py \\
    --local http://127.0.0.1:8765 \\
    --remote http://100.122.106.124

  # With auth for protected snapshot routes:
  OPENFDD_LIVE_ACME=1 python3 scripts/site_parity_smoke.py --remote-limit acme_vm_bbartling
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


@dataclass
class SiteProbe:
    label: str
    base: str
    health: dict[str, Any] = field(default_factory=dict)
    stack: dict[str, Any] = field(default_factory=dict)
    asset_hash: str = ""
    errors: list[str] = field(default_factory=list)


def _fetch_json(url: str, *, token: str | None = None, timeout: float = 30.0) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:500]}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {"error": str(exc)}


def _fetch_text(url: str, timeout: float = 30.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")[:2000]
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, str(exc)


def _asset_from_html(html: str) -> str:
    m = re.search(r'/assets/(index-[^"\']+\.js)', html)
    return m.group(1) if m else ""


def _login(base: str, user: str, password: str) -> str | None:
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/auth/login",
        data=json.dumps({"username": user, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            payload = json.loads(resp.read().decode())
            return str(payload.get("token") or "") or None
    except Exception:
        return None


def resolve_remote_base(limit: str) -> str:
    sys.path.insert(0, str(REPO))
    from scripts.acme_live_validate import resolve_base_from_ansible  # noqa: E402

    return resolve_base_from_ansible(limit).rstrip("/")


def probe_site(label: str, base: str, *, token: str | None = None) -> SiteProbe:
    out = SiteProbe(label=label, base=base.rstrip("/"))
    st, health = _fetch_json(f"{out.base}/health")
    if st != 200 or not isinstance(health, dict):
        out.errors.append(f"health HTTP {st}")
    else:
        out.health = health

    st2, stack = _fetch_json(f"{out.base}/health/stack", token=token)
    if st2 == 200 and isinstance(stack, dict):
        out.stack = stack
    elif st2 == 401 and token:
        out.errors.append("health/stack auth failed (bad token?)")
    elif st2 not in (200, 401):
        out.errors.append(f"health/stack HTTP {st2}")

    st3, html = _fetch_text(f"{out.base}/")
    if st3 == 200:
        out.asset_hash = _asset_from_html(html)
        if not out.asset_hash:
            out.errors.append("dashboard HTML missing index-*.js asset")
    else:
        out.errors.append(f"dashboard HTML HTTP {st3}")

    return out


def compare(local: SiteProbe, remote: SiteProbe) -> list[str]:
    issues: list[str] = []
    issues.extend(f"[{local.label}] {e}" for e in local.errors)
    issues.extend(f"[{remote.label}] {e}" for e in remote.errors)

    lv = str(local.health.get("openfdd_version") or local.health.get("version") or "")
    rv = str(remote.health.get("openfdd_version") or remote.health.get("version") or "")
    if lv and rv and lv != rv:
        issues.append(f"version mismatch: local={lv} remote={rv}")

    lsha = str(local.health.get("git_sha") or local.stack.get("git_sha") or "")[:12]
    rsha = str(remote.health.get("git_sha") or remote.stack.get("git_sha") or "")[:12]
    if lsha and rsha and lsha != rsha:
        issues.append(f"git_sha mismatch: local={lsha} remote={rsha}")

    if local.asset_hash and remote.asset_hash and local.asset_hash != remote.asset_hash:
        issues.append(
            f"UI bundle mismatch: local={local.asset_hash} remote={remote.asset_hash} "
            "(run upgrade_edge_full.sh to sync static/app)"
        )

    ltag = str(local.stack.get("image_tag") or "")
    rtag = str(remote.stack.get("image_tag") or "")
    if ltag and rtag and ltag != rtag:
        issues.append(f"image_tag mismatch: local={ltag} remote={rtag}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", default=os.environ.get("OPENFDD_LOCAL_BASE", "http://127.0.0.1:8765"))
    parser.add_argument("--remote", default=os.environ.get("OPENFDD_REMOTE_BASE", ""))
    parser.add_argument("--remote-limit", default=os.environ.get("OPENFDD_ANSIBLE_LIMIT", "acme_vm_bbartling"))
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    remote_base = args.remote.strip() or resolve_remote_base(args.remote_limit)

    token: str | None = None
    auth_env = REPO / "workspace" / "auth.env.local"
    acme_secrets = REPO / "infra/ansible/secrets/acme.env.local"
    if os.environ.get("OPENFDD_LIVE_ACME") == "1" and auth_env.is_file():
        sys.path.insert(0, str(REPO))
        from scripts.acme_live_validate import load_env_file, resolve_credentials  # noqa: E402

        user, password = resolve_credentials(auth_env, acme_secrets if acme_secrets.is_file() else None)
        if user and password:
            token = _login(args.local.rstrip("/"), user, password)

    local = probe_site("bensserver", args.local, token=token)
    remote = probe_site("acme", remote_base, token=token)
    issues = compare(local, remote)

    report = {
        "local": {"base": local.base, "health": local.health, "asset": local.asset_hash, "errors": local.errors},
        "remote": {"base": remote.base, "health": remote.health, "asset": remote.asset_hash, "errors": remote.errors},
        "issues": issues,
        "pass": not issues,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
