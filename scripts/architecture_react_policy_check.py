#!/usr/bin/env python3
"""Phase 1 architecture policy gates (P1-M0-01).

1. Reject production React/TS clients that hardcode Python service bases
   (FastAPI/uvicorn/Streamlit ports or http://...:8501 style UI backends).
2. Reject pandas / Streamlit runtime dependencies in new production frontend
   package manifests (frontend/, web/, apps/web/).
3. Require ADR-001 and migration README to exist once modernization has started.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ADR = ROOT / "docs" / "architecture" / "adr-001-react-rust-modernization.md"
MIG_README = ROOT / "docs" / "migration" / "react-rust" / "README.md"

# Production-ish frontend roots that may appear during Phase 1+.
FRONTEND_ROOTS = (
    ROOT / "frontend",
    ROOT / "web",
    ROOT / "apps" / "web",
    ROOT / "services" / "web",
)

# Patterns that indicate a browser client aimed at a Python UI/API process.
FORBIDDEN_CLIENT_PATTERNS = (
    re.compile(r"localhost:8501", re.I),
    re.compile(r"127\.0\.0\.1:8501", re.I),
    re.compile(r":8501\b"),
    re.compile(r"fastapi", re.I),
    re.compile(r"uvicorn", re.I),
    re.compile(r"streamlit\.io", re.I),
    re.compile(r"STREAMLIT_SERVER", re.I),
    re.compile(r"OPENFDD_PYTHON_API", re.I),
    re.compile(r"VITE_.*PYTHON", re.I),
    re.compile(r"REACT_APP_.*PYTHON", re.I),
)

CLIENT_GLOBS = (
    "**/*.{ts,tsx,js,jsx,mjs,cjs}",
    "**/vite.config.*",
    "**/next.config.*",
    "**/.env*",
)

FORBIDDEN_PKG_DEPS = frozenset(
    {
        "streamlit",
        "pandas",
        "fastapi",
        "uvicorn",
        "flask",
        "django",
    }
)

# Files under frontend that are historical / retired notes — skip scan noise.
SKIP_NAME_PARTS = (
    "/node_modules/",
    "/dist/",
    "/build/",
    "/.next/",
    "/coverage/",
)


def _iter_frontend_files() -> list[Path]:
    files: list[Path] = []
    for root in FRONTEND_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if any(part in f"/{rel}/" or part in rel for part in SKIP_NAME_PARTS):
                continue
            if path.suffix.lower() in {
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".mjs",
                ".cjs",
                ".json",
                ".env",
            } or path.name.startswith(".env") or "vite.config" in path.name or "next.config" in path.name:
                files.append(path)
    return files


def check_adr(errors: list[str]) -> None:
    if not ADR.is_file():
        errors.append(f"missing ADR: {ADR.relative_to(ROOT)}")
        return
    text = ADR.read_text(encoding="utf-8")
    for needle in (
        "React",
        "central",
        "DataFusion",
        "FastAPI",
        "Streamlit",
        "Accepted",
    ):
        if needle not in text:
            errors.append(f"ADR-001 missing required marker {needle!r}")
    if "no FastAPI" not in text.lower() and "No FastAPI" not in text:
        errors.append("ADR-001 must explicitly reject a FastAPI sidecar")
    if not MIG_README.is_file():
        errors.append(f"missing {MIG_README.relative_to(ROOT)}")


def check_react_clients(errors: list[str]) -> None:
    for path in _iter_frontend_files():
        if path.suffix == ".json" and path.name not in {
            "package.json",
            "package-lock.json",
        }:
            # Only scan package.json for deps; skip other JSON.
            if path.name != "package.json":
                continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"unreadable {path}: {exc}")
            continue
        if path.name == "package.json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"invalid package.json {path}: {exc}")
                continue
            deps = {}
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                block = data.get(key) or {}
                if isinstance(block, dict):
                    deps.update(block)
            for name in deps:
                if name.lower() in FORBIDDEN_PKG_DEPS:
                    errors.append(
                        f"{path.relative_to(ROOT)} must not depend on {name!r} "
                        "(production frontend; use Rust/DataFusion)"
                    )
            continue
        # Skip retired README-only frontend without sources
        if path.name == "README.md":
            continue
        for pat in FORBIDDEN_CLIENT_PATTERNS:
            if pat.search(text):
                # Allow comments that say "do not use fastapi"
                line_hits = [
                    ln
                    for ln in text.splitlines()
                    if pat.search(ln)
                    and not re.search(r"\b(not|never|reject|forbid|ban|no)\b", ln, re.I)
                ]
                if line_hits:
                    errors.append(
                        f"{path.relative_to(ROOT)} appears to point a client at a "
                        f"Python service ({pat.pattern})"
                    )
                    break


def check_instruction_alignment(errors: list[str]) -> None:
    """Ensure key instruction files authorize React; Streamlit product tree gone."""
    ui_root = ROOT / "services" / "ui"
    if ui_root.exists():
        errors.append(
            "services/ui must not exist (Streamlit product removed; use frontend/web)"
        )
    frontend_readme = ROOT / "frontend" / "README.md"
    if frontend_readme.is_file():
        text = frontend_readme.read_text(encoding="utf-8")
        if "Do not recreate a React UI here" in text and "Phase 1" not in text:
            errors.append(
                "frontend/README.md must be updated for Phase 1 React authorization"
            )


def main() -> int:
    errors: list[str] = []
    check_adr(errors)
    check_react_clients(errors)
    check_instruction_alignment(errors)
    if errors:
        print("architecture_react_policy_check FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("architecture_react_policy_check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
