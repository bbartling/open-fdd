#!/usr/bin/env python3
"""Read-only host/runtime readiness checks (Wave U UA-08 / Astra A10).

Default: --selftest validates check definitions without touching the host.
With OPENFDD_HOST_RUNTIME_PROBE=1 (or --probe): inspect the current Linux host
for Docker socket exposure, effective SSH PermitRootLogin (including Include
files), listen bind addresses (IPv4/IPv6, TCP/UDP), and Docker publish hints.

Never installs packages or mutates the system. Not a Nessus substitute.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "reports" / "security" / "host_runtime_probe.json"
SCHEMA = "openfdd_host_runtime_probe_v2"

# bind policy: lan_ok | loopback_only | must_absent
PROFILES: dict[str, dict[str, Any]] = {
    # Legacy aliases retained for Wave U callers.
    "standalone_https": {
        "expected_listen": [
            {"proto": "tcp", "port": 443, "bind": "lan_ok", "note": "Caddy HTTPS"},
        ],
        "forbidden_listen": [
            {
                "proto": "tcp",
                "port": 8080,
                "bind": "must_absent",
                "note": "central must not be LAN-published",
            },
        ],
    },
    "field_only_ot": {
        "expected_listen": [],
        "forbidden_listen": [
            {"proto": "tcp", "port": 8080, "bind": "must_absent", "note": "no local central"},
            {"proto": "tcp", "port": 3000, "bind": "must_absent", "note": "no local web"},
            {
                "proto": "tcp",
                "port": 8883,
                "bind": "must_absent",
                "note": "no local MQTT broker listen",
            },
        ],
    },
    # Deployment-contract profiles (Astra A10).
    "cloud_mqtt_hub": {
        "expected_listen": [],
        "forbidden_listen": [
            {
                "proto": "tcp",
                "port": 8080,
                "bind": "must_absent",
                "note": "central not on edge host",
            },
            {
                "proto": "udp",
                "port": 47808,
                "bind": "must_absent",
                "note": "no BACnet on cloud edge host",
            },
        ],
    },
    "ot_local_bacnet_modbus": {
        "expected_listen": [
            {"proto": "tcp", "port": 443, "bind": "lan_ok", "note": "Caddy HTTPS"},
        ],
        "forbidden_listen": [
            {
                "proto": "tcp",
                "port": 8080,
                "bind": "must_absent",
                "note": "central must stay private (not host-published)",
            },
            {
                "proto": "tcp",
                "port": 8883,
                "bind": "must_absent",
                "note": "no local MQTT broker on OT recipe",
            },
        ],
        "optional_listen": [
            {
                "proto": "tcp",
                "port": 8081,
                "bind": "loopback_only",
                "note": "connector management loopback",
            },
            {
                "proto": "udp",
                "port": 47808,
                "bind": "lan_ok",
                "note": "BACnet/IP when connector selected",
            },
        ],
    },
    "ot_local_haystack": {
        "expected_listen": [
            {"proto": "tcp", "port": 443, "bind": "lan_ok", "note": "Caddy HTTPS"},
        ],
        "forbidden_listen": [
            {
                "proto": "tcp",
                "port": 8080,
                "bind": "must_absent",
                "note": "central must stay private (not host-published)",
            },
            {
                "proto": "udp",
                "port": 47808,
                "bind": "must_absent",
                "note": "Haystack-only must not own BACnet UDP",
            },
            {
                "proto": "tcp",
                "port": 8883,
                "bind": "must_absent",
                "note": "no local MQTT broker on OT recipe",
            },
        ],
    },
    "local_development": {
        "expected_listen": [],
        "forbidden_listen": [],
        "notes": "lab only — never readiness/Nessus qualification",
    },
}

_SS_ADDR = re.compile(
    r"(?P<addr>\*|\[::\]|::|0\.0\.0\.0|127\.0\.0\.1|\[::1\]|::1|"
    r"\d+\.\d+\.\d+\.\d+|\[[0-9a-fA-F:]+\]):(?P<port>\d+)\s"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(cid: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"id": cid, "ok": ok, "detail": detail}


def classify_bind(addr: str) -> str:
    """Return loopback | wildcard | unicast for a listen address."""
    a = (addr or "").strip().lower()
    if a in {"127.0.0.1", "::1", "[::1]"}:
        return "loopback"
    if a in {"*", "0.0.0.0", "::", "[::]"}:
        return "wildcard"
    return "unicast"


def bind_policy_ok(policy: str, binds: list[str]) -> tuple[bool, str]:
    """Evaluate listen addresses against bind policy."""
    classes = {classify_bind(b) for b in binds}
    if policy == "must_absent":
        return (len(binds) == 0, f"binds={binds or 'none'}")
    if policy == "loopback_only":
        if not binds:
            return True, "not_listening (optional)"
        bad = [b for b in binds if classify_bind(b) != "loopback"]
        return (not bad, f"binds={binds}")
    if policy == "lan_ok":
        if not binds:
            return False, "not_listening"
        return True, f"binds={binds}"
    return False, f"unknown policy {policy!r}"


def selftest_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required = {
        "standalone_https",
        "field_only_ot",
        "cloud_mqtt_hub",
        "ot_local_bacnet_modbus",
        "ot_local_haystack",
        "local_development",
    }
    checks.append(
        _check(
            "profiles_cover_deployment_contract",
            required.issubset(PROFILES),
            f"have={sorted(PROFILES)}",
        )
    )
    for name, profile in PROFILES.items():
        checks.append(
            _check(
                f"profile_{name}_defined",
                "forbidden_listen" in profile,
                f"forbidden={len(profile.get('forbidden_listen') or [])}",
            )
        )

    # Negative: empty forbidden is insufficient for field_only.
    bad = {"forbidden_listen": []}
    checks.append(
        _check(
            "negative_empty_forbidden_rejected",
            not bool(bad.get("forbidden_listen")),
            "empty forbidden list is insufficient for field_only",
        )
    )
    ports = {p["port"] for p in PROFILES["field_only_ot"]["forbidden_listen"]}
    checks.append(_check("field_only_forbids_8080", 8080 in ports, f"ports={sorted(ports)}"))
    checks.append(
        _check(
            "standalone_expects_443",
            any(p["port"] == 443 for p in PROFILES["standalone_https"]["expected_listen"]),
            "443",
        )
    )
    # Haystack must forbid BACnet UDP ownership.
    hay_udp = [
        p
        for p in PROFILES["ot_local_haystack"]["forbidden_listen"]
        if p.get("proto") == "udp" and p.get("port") == 47808
    ]
    checks.append(_check("haystack_forbids_bacnet_udp", bool(hay_udp), str(hay_udp)))

    # Bind classification unit checks (no host I/O).
    checks.append(_check("bind_loopback", classify_bind("127.0.0.1") == "loopback", "127.0.0.1"))
    checks.append(_check("bind_wildcard", classify_bind("0.0.0.0") == "wildcard", "0.0.0.0"))
    ok_pol, _ = bind_policy_ok("must_absent", ["0.0.0.0"])
    checks.append(_check("policy_must_absent_rejects_wildcard", not ok_pol, "wildcard"))
    ok_pol, _ = bind_policy_ok("loopback_only", ["127.0.0.1"])
    checks.append(_check("policy_loopback_accepts_local", ok_pol, "127.0.0.1"))
    ok_pol, _ = bind_policy_ok("loopback_only", ["0.0.0.0"])
    checks.append(_check("policy_loopback_rejects_wildcard", not ok_pol, "0.0.0.0"))

    # SSH Include parser on synthetic text.
    syn = "Include /tmp/openfdd_sshd_dropin.conf\nPermitRootLogin yes\n"
    vals = parse_ssh_permit_root_values(syn, reader=lambda p: "PermitRootLogin no\n")
    checks.append(
        _check(
            "ssh_include_effective_no",
            "no" in vals and "yes" in vals,
            f"values={sorted(vals)}",
        )
    )
    return checks


def _ss_listen_binds(port: int, proto: str = "tcp") -> list[str] | None:
    """Return listen bind addresses for port; None if ss unavailable."""
    if not shutil.which("ss"):
        return None
    flag = "-ltn" if proto == "tcp" else "-lun"
    try:
        out = subprocess.check_output(["ss", flag], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    binds: list[str] = []
    for line in out.splitlines():
        m = _SS_ADDR.search(line + " ")
        if not m:
            # Fallback needle for odd ss formats.
            if f":{port} " in line or line.rstrip().endswith(f":{port}"):
                binds.append("*")
            continue
        if int(m.group("port")) != port:
            continue
        binds.append(m.group("addr"))
    return binds


def _ss_listening(port: int, proto: str = "tcp") -> bool | None:
    binds = _ss_listen_binds(port, proto)
    if binds is None:
        return None
    return len(binds) > 0


def _docker_socket_world_writable() -> bool | None:
    path = Path("/var/run/docker.sock")
    if not path.exists():
        return False
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return None
    return bool(mode & 0o002)


def parse_ssh_permit_root_values(
    text: str,
    *,
    reader: Any | None = None,
    _seen: set[str] | None = None,
) -> set[str]:
    """Collect PermitRootLogin values from text + Include files."""
    values: set[str] = set()
    seen = _seen if _seen is not None else set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) >= 2 and parts[0].lower() == "include":
            pattern = parts[1]
            # Only expand literal paths in readiness probe (no shell glob exec).
            path = Path(pattern)
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if reader is not None:
                try:
                    values |= parse_ssh_permit_root_values(
                        reader(path), reader=reader, _seen=seen
                    )
                except OSError:
                    continue
            elif path.is_file():
                try:
                    values |= parse_ssh_permit_root_values(
                        path.read_text(encoding="utf-8", errors="replace"),
                        reader=reader,
                        _seen=seen,
                    )
                except OSError:
                    continue
            continue
        if len(parts) >= 2 and parts[0].lower() == "permitrootlogin":
            values.add(parts[1].lower())
    return values


def _ssh_permit_root_effective() -> tuple[str | None, list[str]]:
    cfg = Path("/etc/ssh/sshd_config")
    if not cfg.is_file():
        return None, []
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, []
    values = parse_ssh_permit_root_values(text)
    if not values:
        return "unset", []
    # Prefer the most permissive observed value for fail-closed readiness.
    order = ["yes", "prohibit-password", "without-password", "forced-commands-only", "no", "unset"]
    for candidate in order:
        if candidate in values:
            return candidate, sorted(values)
    return sorted(values)[0], sorted(values)


def _docker_publish_hint() -> dict[str, Any]:
    """Best-effort Docker publish / firewall readiness hint (not Nessus)."""
    detail: dict[str, Any] = {"docker0": False, "iptables_docker_chain": None}
    detail["docker0"] = Path("/sys/class/net/docker0").exists()
    if shutil.which("iptables"):
        try:
            out = subprocess.check_output(
                ["iptables", "-S", "DOCKER"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            detail["iptables_docker_chain"] = "present" if out.strip() else "empty"
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            detail["iptables_docker_chain"] = "unavailable"
    else:
        detail["iptables_docker_chain"] = "iptables_missing"
    return detail


def _evaluate_listen_item(item: dict[str, Any], *, required: bool) -> dict[str, Any]:
    port = int(item["port"])
    proto = item.get("proto", "tcp")
    policy = item.get("bind", "must_absent" if not required else "lan_ok")
    cid = f"{'expected' if required else 'forbidden'}_listen_{proto}_{port}"
    binds = _ss_listen_binds(port, proto)
    if binds is None:
        # Fall back to localhost connect for TCP only — does not prove LAN exposure.
        if proto != "tcp":
            return _check(
                cid,
                True if not required else False,
                f"{item.get('note')}; ss missing — UDP bind unknown",
            )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            listening = sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()
        if policy == "must_absent":
            return _check(
                cid,
                not listening,
                f"{item.get('note')}; localhost_connect={listening} (ss missing)",
            )
        if not required and not listening:
            return _check(cid, True, f"{item.get('note')}; not listening (ss missing)")
        return _check(
            cid,
            True,
            f"{item.get('note')}; localhost_connect={listening} (ss missing; LAN unknown)",
        )
    ok, detail = bind_policy_ok(policy, binds)
    if not required and policy != "must_absent" and not binds:
        ok = True
        detail = "not_listening (optional)"
    return _check(cid, ok, f"{item.get('note')}; {detail}")


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

    root_login, all_vals = _ssh_permit_root_effective()
    if root_login is None:
        checks.append(_check("ssh_permit_root_login", True, "sshd_config absent (N/A)"))
    else:
        ok = root_login in {"no", "prohibit-password", "without-password", "unset"}
        checks.append(
            _check(
                "ssh_permit_root_login",
                ok or root_login == "without-password",
                f"effective={root_login} observed={all_vals or [root_login]}",
            )
        )

    docker_hint = _docker_publish_hint()
    checks.append(
        _check(
            "docker_publish_path_observed",
            True,
            json.dumps(docker_hint, sort_keys=True),
        )
    )

    for item in prof.get("forbidden_listen") or []:
        checks.append(_evaluate_listen_item(item, required=False))
    for item in prof.get("expected_listen") or []:
        checks.append(_evaluate_listen_item(item, required=True))
    for item in prof.get("optional_listen") or []:
        # Optional: only fail if bind policy violated while listening.
        port = int(item["port"])
        proto = item.get("proto", "tcp")
        policy = item.get("bind", "loopback_only")
        binds = _ss_listen_binds(port, proto)
        cid = f"optional_listen_{proto}_{port}"
        if binds is None:
            checks.append(
                _check(cid, True, f"{item.get('note')}; ss missing — skipped")
            )
            continue
        if not binds:
            checks.append(_check(cid, True, f"{item.get('note')}; not_listening"))
            continue
        ok, detail = bind_policy_ok(policy, binds)
        checks.append(_check(cid, ok, f"{item.get('note')}; {detail}"))
    return checks


def run(mode: str, profile: str) -> dict[str, Any]:
    if mode == "selftest":
        checks = selftest_checks()
        profile_out = profile
    else:
        if profile not in PROFILES:
            raise SystemExit(f"unknown profile {profile}")
        checks = probe_host(profile)
        profile_out = profile
    ok = all(c["ok"] for c in checks)
    return {
        "schema_version": SCHEMA,
        "mode": mode,
        "profile": profile_out,
        "ok": ok,
        "verdict": "PASS" if ok else "FAIL",
        "checked_at": _now(),
        "checks": checks,
        "notes": "Host readiness evidence only — not Nessus, not FQ.",
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
    probe_env = os.environ.get("OPENFDD_HOST_RUNTIME_PROBE", "").strip() in {
        "1",
        "true",
        "yes",
    }
    mode = "probe" if (args.probe or probe_env) else "selftest"
    report = run(mode, args.profile)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
