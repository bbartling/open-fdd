#!/usr/bin/env python3
"""Regenerate services/central/openapi_router_routes.json from Axum router sources."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CENTRAL_SRC = REPO / "services" / "central" / "src"
OUT = REPO / "services" / "central" / "openapi_router_routes.json"

ROUTE_SOURCE_FILES = [
    "routes.rs",
    "afdd_scheduler.rs",
    "product_schedules.rs",
    "sql_anomaly.rs",
    "cutover.rs",
    "vibe21.rs",
]

METHODS = ("get", "post", "put", "patch", "delete")


def strip_cfg_test_modules(text: str) -> str:
    out: list[str] = []
    cursor = 0
    while cursor < len(text):
        rel = text.find("#[cfg(test)]", cursor)
        if rel < 0:
            out.append(text[cursor:])
            break
        cfg_start = rel
        out.append(text[cursor:cfg_start])
        after = cfg_start + len("#[cfg(test)]")
        mod_rel = text.find("mod ", after)
        if mod_rel < 0:
            out.append("#[cfg(test)]")
            cursor = after
            continue
        between = text[after:mod_rel]
        if not all(c.isspace() for c in between):
            out.append("#[cfg(test)]")
            cursor = after
            continue
        mod_start = mod_rel
        brace = text.find("{", mod_start)
        if brace < 0:
            out.append(text[cfg_start:after])
            cursor = after
            continue
        depth = 0
        block_end = None
        for i in range(brace, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    block_end = i
                    break
        if block_end is None:
            out.append(text[cfg_start : brace + 1])
            cursor = brace + 1
            continue
        cursor = block_end + 1
    return "".join(out)


def parse_route_call(text: str) -> tuple[str, int] | None:
    i = 0
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] != '"':
        return None
    i += 1
    path_start = i
    while i < len(text) and text[i] != '"':
        i += 1
    if i >= len(text):
        return None
    path = text[path_start:i]
    i += 1
    depth = 1
    while i < len(text) and depth > 0:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    return path, i


def handler_start_offset(after_path: str) -> int:
    i = 0
    while i < len(after_path) and after_path[i].isspace():
        i += 1
    if i < len(after_path) and after_path[i] == ",":
        i += 1
    while i < len(after_path) and after_path[i].isspace():
        i += 1
    return i


def infer_methods(handler: str) -> list[str]:
    found: list[str] = []
    for method in METHODS:
        if f"{method}(" in handler or f"routing::{method}(" in handler:
            found.append(method.upper())
    return found


def parse_routes_from_source(text: str) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    search_from = 0
    needle = ".route("
    while True:
        rel = text.find(needle, search_from)
        if rel < 0:
            break
        start = rel + len(needle)
        parsed = parse_route_call(text[start:])
        if not parsed:
            search_from = start
            continue
        api_path, handler_end = parsed
        if api_path.startswith("/api"):
            h_off = handler_start_offset(text[start:])
            handler = text[start + h_off : start + handler_end]
            for method in infer_methods(handler):
                routes.add((method, api_path))
        search_from = start + handler_end
    return routes


def collect_from_sources() -> list[dict[str, str]]:
    all_routes: set[tuple[str, str]] = set()
    for name in ROUTE_SOURCE_FILES:
        path = CENTRAL_SRC / name
        text = path.read_text(encoding="utf-8")
        production = strip_cfg_test_modules(text)
        all_routes |= parse_routes_from_source(production)
    entries = [{"method": m, "path": p} for m, p in sorted(all_routes)]
    return entries


def main() -> int:
    entries = collect_from_sources()
    payload = {
        "schema_version": "openfdd_openapi_router_routes_v1",
        "entries": entries,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} routes to {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
