"""Resolve BACnet/IP bind address for BACpypes3 (--address IP/prefix:47808).

BACpypes3 must bind the host NIC IP (e.g. 192.168.204.12/24), not 127.0.0.1, for
LAN Who-Is/I-Am to work — see bacpypes3 shell discussions (Who-Is only works when
the stack is on the same broadcast domain as field devices).
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
from typing import Iterable

_DEFAULT_PORT = 47808
_LOOPBACK = frozenset({"127.0.0.1", "0.0.0.0", "::1", "0:0:0:0:0:0:0:1"})


def _parse_ip_addr_show() -> list[tuple[str, int]]:
    """Parse `ip -4 -o addr show scope global` → [(ip, prefix_len), ...]."""
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[tuple[str, int]] = []
    for line in out.splitlines():
        parts = line.split()
        # inet 192.168.204.12/24 brd ...
        for token in parts:
            if "/" in token and token.count(".") == 3:
                ip_part, _, prefix = token.partition("/")
                try:
                    ipaddress.IPv4Address(ip_part)
                    rows.append((ip_part, int(prefix)))
                except ValueError:
                    continue
                break
    return rows


def _outbound_guess() -> tuple[str, int] | None:
    """Best-effort LAN IP via UDP connect (no packets sent)."""
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if ip and ip not in _LOOPBACK:
            return ip, 24
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()
    return None


def _prefer_lan_address(candidates: list[tuple[str, int]]) -> tuple[str, int] | None:
    private = [(ip, plen) for ip, plen in candidates if ipaddress.IPv4Address(ip).is_private]
    if private:
        return private[0]
    return candidates[0] if candidates else None


def detect_lan_ipv4(*, prefer_prefix: Iterable[str] = ("192.168.", "10.", "172.")) -> tuple[str, int] | None:
    """Pick the first plausible OT/LAN IPv4 address on this host."""
    candidates = _parse_ip_addr_show()
    if not candidates:
        guess = _outbound_guess()
        candidates = [guess] if guess else []
    if not candidates:
        return None
    private = [(ip, plen) for ip, plen in candidates if ipaddress.IPv4Address(ip).is_private]
    pool = private or candidates
    for prefix in prefer_prefix:
        if prefix == "172.":
            for ip, plen in pool:
                if ipaddress.IPv4Address(ip) in ipaddress.ip_network("172.16.0.0/12"):
                    return ip, plen
            continue
        for ip, plen in pool:
            if ip.startswith(prefix):
                return ip, plen
    return _prefer_lan_address(pool)


def normalize_bacnet_bind(raw: str, *, default_port: int = _DEFAULT_PORT) -> str:
    """Normalize commission.env BACNET_BIND to BACpypes3 --address form."""
    text = (raw or "").strip()
    if not text:
        return text
    # already host/prefix:port
    if re.match(r"^[\d.]+/\d+:\d+$", text):
        return text
    # host/prefix without port
    if re.match(r"^[\d.]+/\d+$", text):
        return f"{text}:{default_port}"
    # host:port only (legacy)
    if re.match(r"^[\d.]+:\d+$", text) and "/" not in text:
        host, _, port = text.partition(":")
        return f"{host}/24:{port}"
    # bare IP
    if re.match(r"^[\d.]+$", text):
        return f"{text}/24:{default_port}"
    return text


def _bind_host(raw: str) -> str:
    text = normalize_bacnet_bind(raw)
    if not text:
        return ""
    host = text.split("/")[0].split(":")[0]
    return host


def should_auto_resolve_bind(raw: str) -> bool:
    if os.environ.get("OFDD_BACNET_BIND_STRICT", "").strip().lower() in {"1", "true", "yes"}:
        return False
    host = _bind_host(raw)
    return not host or host in _LOOPBACK


def resolve_bacnet_bind(raw: str | None = None, *, default_port: int = _DEFAULT_PORT) -> str:
    """Return BACpypes3 --address value; auto-detect NIC when bind is loopback/empty."""
    env_override = os.environ.get("OFDD_BACNET_BIND", "").strip()
    candidate = (raw or env_override or "").strip()
    if candidate and not should_auto_resolve_bind(candidate):
        return normalize_bacnet_bind(candidate, default_port=default_port)
    detected = detect_lan_ipv4()
    if detected:
        ip, prefix = detected
        return f"{ip}/{prefix}:{default_port}"
    if candidate:
        return normalize_bacnet_bind(candidate, default_port=default_port)
    return f"0.0.0.0/24:{default_port}"


def _iface_name_from_ip_addr_line(line: str) -> str:
    parts = line.split()
    if len(parts) >= 2:
        return parts[1].rstrip(":")
    return ""


def list_host_interfaces() -> list[dict[str, str | bool]]:
    """List IPv4 interfaces for BACnet bind UI (host-side, read-only)."""
    rows: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        iface = _iface_name_from_ip_addr_line(line)
        for token in line.split():
            if "/" not in token or token.count(".") != 3:
                continue
            ip_part, _, prefix = token.partition("/")
            try:
                addr = ipaddress.IPv4Address(ip_part)
            except ValueError:
                continue
            key = f"{iface}:{ip_part}"
            if key in seen:
                continue
            seen.add(key)
            kind = "lan"
            if addr.is_loopback:
                kind = "loopback"
            elif str(ip_part).startswith("100."):
                kind = "tailscale"
            elif iface.startswith("docker") or iface.startswith("br-"):
                kind = "docker"
            label = iface or "interface"
            if kind == "tailscale":
                label = f"Tailscale — {ip_part}"
            elif kind == "loopback":
                label = f"Loopback — {ip_part}"
            elif kind == "docker":
                label = f"Docker — {iface} ({ip_part})"
            else:
                label = f"{iface} — {ip_part}"
            rows.append(
                {
                    "interface": iface,
                    "ipv4": ip_part,
                    "prefix_len": prefix,
                    "cidr": f"{ip_part}/{prefix}",
                    "kind": kind,
                    "label": label,
                    "is_private": addr.is_private,
                }
            )
    rows.sort(key=lambda r: (str(r.get("kind")), str(r.get("interface"))))
    return rows


def resolve_commission_cfg(cfg: dict[str, str]) -> dict[str, str]:
    """Apply bind + name defaults in-place on a commission config dict."""
    out = dict(cfg)
    out["BACNET_BIND"] = resolve_bacnet_bind(out.get("BACNET_BIND"))
    from bacnet_toolshed.device_identity import apply_device_identity_defaults

    return apply_device_identity_defaults(out)
