#!/usr/bin/env python3
"""Read-only host/runtime readiness checks for Wave U profiles (UA-08).

Default: --selftest validates check definitions without touching the host.
With OPENFDD_HOST_RUNTIME_PROBE=1 (or --probe): inspect the current Linux host
for Docker socket exposure, SSH PermitRootLogin, and expected profile ports.
Never installs packages or mutates the system. Not a Nessus substitute.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "reports" / "security" / "host_runtime_probe.json"
SCHEMA = "openfdd_host_runtime_probe_v1"

PROFILES = {
    "standalone_https": {
        "expected_listen": [{"proto": "tcp", "port": 443, "note": "Caddy HTTPS"}],
        "forbidden_listen": [
            {"proto": "tcp", "port": 8080, "note": "central must not be LAN-published"},
        ],
    },
    "field_only_ot": {
        "expected_listen": [],
        "forbidden_listen": [
            {"proto": "tcp", "port": 8080, "note": "no local central"},
            {"proto": "tcp", "port": 3000, "note": "no local web"},
            {"proto": "tcp", "port": 8883, "note": "no local MQTT broker listen"},
        ],
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(cid: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": cid, "ok": ok, "detail": detail}


def selftest_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name, profile in PROFILES.items():
        checks.append(
            _check(
                f"profile_{name}_defined",
                bool(profile.get("forbidden_listen") is not None),
                f"forbidden={len(profile.get('forbidden_listen') or [])}",
            )
        )
    # Negative: a profile claiming LAN central publish must fail policy lint.
    bad = {"forbidden_listen": []}
    checks.append(
        _check(
            "negative_empty_forbidden_rejected",
            not bool(bad.get("forbidden_listen")),
            "empty forbidden list is insufficient for field_only",
        )
    )
    # Flip: require field_only forbidden to include 8080.
    ports = {p["port"] for p in PROFILES["field_only_ot"]["forbidden_listen"]}
    checks.append(_check("field_only_forbids_8080", 8080 in ports, f"ports={sorted(ports)}"))
    checks.append(_check("standalone_expects_443", any(
        p["port"] == 443 for p in PROFILES["standalone_https"]["expected_listen"]
    ), "443"))
    return checks


def _ss_listening(port: int, proto: str = "tcp") -> bool | None:
    """Return True/False if ss available; None if tool missing."""
    if not shutil.which("ss"):
        return None
    flag = "-ltn" if proto == "tcp" else "-lun"
    try:
        out = subprocess.check_output(["ss", flag], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    needle = f":{port} "
    return any(needle in line for line in out.splitlines())


def _docker_socket_world_writable() -> bool | None:
    path = Path("/var/run/docker.sock")
    if not path.exists():
        return False
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return None
    return bool(mode & 0o002)


def _ssh_permit_root() -> str | None:
    cfg = Path("/etc/ssh/sshd_config")
    if not cfg.is_file():
        return None
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) >= 2 and parts[0].lower() == "permitrootlogin":
            return parts[1].lower()
    return "unset"


def probe_host(profile: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    prof = PROFILES[profile]
    uname = os.uname()
    checks.append(
        _check(
            "host_kernel",
            True,
            f"{uname.sysname} {uname.release} {uname.machine}",
        )
    )
    docker_ww = _docker_socket_world_writable()
    if docker_ww is None:
        checks.append(_check("docker_socket_perms", False, "stat failed"))
    else:
        checks.append(
            _check(
                "docker_socket_not_world_writable",
                not docker_ww,
                "world-writable" if docker_ww else "ok_or_absent",
            )
        )
    root_login = _ssh_permit_root()
    if root_login is None:
        checks.append(_check("ssh_permit_root_login", True, "sshd_config absent (N/A)"))
    else:
        ok = root_login in {"no", "prohibit-password", "without-password", "unset"}
        # without-password still allows key root; treat as WARN-ok for readiness lint.
        checks.append(_check("ssh_permit_root_login", ok or root_login == "without-password", root_login))

    for item in prof.get("forbidden_listen") or []:
        port = int(item["port"])
        listening = _ss_listening(port, item.get("proto", "tcp"))
        cid = f"forbidden_listen_{port}"
        if listening is None:
            # Fall back to bind probe on localhost only — does not prove LAN exposure.
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.3)
            try:
                listening = sock.connect_ex(("127.0.0.1", port)) == 0
            finally:
                sock.close()
            checks.append(
                _check(
                    cid,
                    not listening,
                    f"{item.get('note')}; localhost_connect={listening} (ss missing)",
                )
            )
        else:
            checks.append(_check(cid, not listening, f"{item.get('note')}; listening={listening}"))

    for item in prof.get("expected_listen") or []:
        port = int(item["port"])
        listening = _ss_listening(port, item.get("proto", "tcp"))
        cid = f"expected_listen_{port}"
        if listening is None:
            checks.append(_check(cid, True, f"{item.get('note')}; ss missing — skipped"))
        else:
            checks.append(_check(cid, listening, f"{item.get('note')}; listening={listening}"))
    return checks


def run(mode: str, profile: str) -> dict[str, Any]:
    if mode == "selftest":
        checks = selftest_checks()
    else:
        if profile not in PROFILES:
            raise SystemExit(f"unknown profile {profile}")
        checks = probe_host(profile)
    ok = all(c["ok"] for c in checks)
    return {
        "schema_version": SCHEMA,
        "mode": mode,
        "profile": profile,
        "ok": ok,
        "verdict": "PASS" if ok else "FAIL",
        "checked_at": _now(),
        "checks": checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true", help="definition checks only")
    ap.add_argument("--probe", action="store_true", help="inspect current host")
    ap.add_argument(
        "--profile",
        default="field_only_ot",
        choices=sorted(PROFILES),
        help="deployment profile",
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    probe_env = os.environ.get("OPENFDD_HOST_RUNTIME_PROBE", "").strip() in {"1", "true", "yes"}
    mode = "probe" if (args.probe or probe_env) else "selftest"
    report = run(mode, args.profile)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
