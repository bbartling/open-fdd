#!/usr/bin/env python3
"""P2-M1 computation / no-Python product policy gates.

Fails if the React no-Python product path still ships a legacy UI service,
enables pandas FDD/oracle flags on that compose file, or if central production
sources spawn/import python/pandas runtimes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_REACT = ROOT / "docker" / "compose.react.yml"
CLOSURE = ROOT / "docs" / "migration" / "react-rust" / "COMPUTATION_CLOSURE.md"
CENTRAL_SRC = ROOT / "services" / "central" / "src"

FORBIDDEN_ENV = (
    "OPENFDD_ALLOW_PANDAS_FDD",
    "OPENFDD_ANALYTICS_ORACLE",
)

FORBIDDEN_COMPOSE_MARKERS = (
    re.compile(r"image:\s*.*openfdd-ui", re.I),
    re.compile(r"services/ui", re.I),
    re.compile(r":8501\b"),
    re.compile(r"\b_stcore\b", re.I),
    re.compile(r"import\s+streamlit", re.I),
)

FORBIDDEN_CENTRAL = (
    re.compile(r"\bpandas\b", re.I),
    re.compile(r"""Command::new\(\s*["'](?:python3?|pip3?|streamlit)["']""", re.I),
    re.compile(r"""["'](?:python3?|pip3?)\s+-[cm]""", re.I),
    re.compile(r"std::process::Command", re.I),
)


def _strip_yaml_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "#" in line:
            code, _, _ = line.partition("#")
            lines.append(code)
        else:
            lines.append(line)
    return "\n".join(lines)


def check_compose_react(errors: list[str]) -> None:
    if not COMPOSE_REACT.is_file():
        errors.append(f"missing {COMPOSE_REACT.relative_to(ROOT)}")
        return
    raw = COMPOSE_REACT.read_text(encoding="utf-8")
    text = _strip_yaml_comments(raw)
    if re.search(r"(?m)^  ui:\s*$", text):
        errors.append("compose.react.yml must not define a legacy `ui` service")
    for pat in FORBIDDEN_COMPOSE_MARKERS:
        if pat.search(text):
            errors.append(
                f"compose.react.yml must not reference forbidden UI marker {pat.pattern!r}"
            )
    for env in FORBIDDEN_ENV:
        if env in text:
            errors.append(f"compose.react.yml must not set {env}")


def check_closure_ledger(errors: list[str]) -> None:
    if not CLOSURE.is_file():
        errors.append(f"missing {CLOSURE.relative_to(ROOT)}")
        return
    text = CLOSURE.read_text(encoding="utf-8")
    for needle in ("CLOSED", "ORACLE", "PROVISIONAL", "sql_screening"):
        if needle not in text:
            errors.append(f"COMPUTATION_CLOSURE.md missing required marker {needle!r}")


def check_central_src(errors: list[str]) -> None:
    if not CENTRAL_SRC.is_dir():
        errors.append("missing services/central/src")
        return
    for path in CENTRAL_SRC.rglob("*.rs"):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"unreadable {rel}: {exc}")
            continue
        for pat in FORBIDDEN_CENTRAL:
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue
                if not pat.search(line):
                    continue
                if re.search(
                    r"\b(forbid|forbidden|ban|banned|never|not|reject|must not|policy|deny)\b",
                    line,
                    re.I,
                ):
                    continue
                errors.append(
                    f"{rel}:{i} matches forbidden runtime marker {pat.pattern!r}: {stripped}"
                )


def main() -> int:
    errors: list[str] = []
    check_compose_react(errors)
    check_closure_ledger(errors)
    check_central_src(errors)
    if errors:
        print("phase2_computation_policy_check FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("phase2_computation_policy_check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
