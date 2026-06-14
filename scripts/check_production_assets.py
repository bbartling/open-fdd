#!/usr/bin/env python3
"""Fail CI if production dashboard assets embed private LAN or bench-specific defaults."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ASSET_DIR = REPO / "workspace" / "api" / "static" / "app" / "assets"

# W3C / schema URLs and other third-party namespaces allowed in minified vendor code.
ALLOWLIST_SUBSTRINGS = (
    "http://www.w3.org/",
    "https://www.w3.org/",
    "http://schemas.openxmlformats.org/",
    "https://brickschema.org/",
    "https://jsonplaceholder.typicode.com/",
    "https://api.example.com/",
    "https://niagara.example.local",
    "https://github.com/",
    "https://www.home-assistant.io/",
)

# Bench / deployment-specific strings that must never ship in operator UI assets.
BANNED_LITERALS = (
    "192.168.204.11",
    "192.168.204.18",
    "Bench Station 9065",
    "BENS$20BENCHTEST$20BOX",
    "bench9065",
    "OPENFDD_NIAGARA_ADMIN_PASSWORD",
)

PRIVATE_IP_PATTERNS = (
    re.compile(r"192\.168\.\d{1,3}\.\d{1,3}"),
    re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
)

# ws:// is never needed in production SPA assets.
BANNED_PROTOCOL = re.compile(r"ws://", re.IGNORECASE)

# Hardcoded backend URLs (SPA should use same-origin relative paths).
HARDCODED_HTTP = re.compile(r"https?://(?:192\.168|10\.|172\.(?:1[6-9]|2\d|3[01])\.)\S+", re.IGNORECASE)


def _is_allowed_context(text: str, start: int, length: int) -> bool:
    window = text[max(0, start - 80) : start + length + 80]
    return any(token in window for token in ALLOWLIST_SUBSTRINGS)


def scan_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    issues: list[str] = []

    for literal in BANNED_LITERALS:
        if literal in text:
            issues.append(f"{path.name}: banned literal {literal!r}")

    for pat in PRIVATE_IP_PATTERNS:
        for m in pat.finditer(text):
            if _is_allowed_context(text, m.start(), len(m.group(0))):
                continue
            issues.append(f"{path.name}: private IP {m.group(0)!r}")

    if BANNED_PROTOCOL.search(text):
        issues.append(f"{path.name}: contains ws://")

    for m in HARDCODED_HTTP.finditer(text):
        issues.append(f"{path.name}: hardcoded URL {m.group(0)!r}")

    return issues


def main() -> int:
    if not ASSET_DIR.is_dir():
        print(f"Asset dir missing: {ASSET_DIR} — run dashboard production build first", file=sys.stderr)
        return 1

    assets = sorted(ASSET_DIR.glob("*.js")) + sorted(ASSET_DIR.glob("*.css"))
    if not assets:
        print(f"No JS/CSS assets in {ASSET_DIR}", file=sys.stderr)
        return 1

    all_issues: list[str] = []
    for asset in assets:
        all_issues.extend(scan_file(asset))

    if all_issues:
        print("Production asset security scan FAILED:", file=sys.stderr)
        for issue in all_issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(f"Production asset security scan OK ({len(assets)} file(s) in {ASSET_DIR})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
