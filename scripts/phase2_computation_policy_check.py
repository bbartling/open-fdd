#!/usr/bin/env python3
"""Wave J computation / no-Python product policy gates.

Fails if product compose files enable retired pandas/oracle flags, or if product
service sources spawn/import Python/pandas runtimes.

Use ``--self-test`` to assert intentional fail fixtures fail the gate (CI).
External PyPI / oracle / tools trees are not scanned as product runtime.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("PHASE2_POLICY_ROOT", Path(__file__).resolve().parents[1]))

FORBIDDEN_ENV = (
    "OPENFDD_ALLOW_PANDAS_FDD",
    "OPENFDD_ANALYTICS_ORACLE",
)

PRODUCT_COMPOSE_REL = (
    "docker/compose.react.yml",
    "docker/compose.react.fieldbus.yml",
    "docker/compose.central.yml",
    "docker/compose.standalone.yml",
    "docker/compose.caddy.react.yml",
    "docker/compose.wattlab.react.yml",
    "docker/compose.web.local-overview.yml",
)

FORBIDDEN_COMPOSE_MARKERS = (
    re.compile(r"image:\s*.*openfdd-ui", re.I),
    re.compile(r"services/ui", re.I),
    re.compile(r":8501\b"),
    re.compile(r"\b_stcore\b", re.I),
    re.compile(r"import\s+streamlit", re.I),
)

PRODUCT_SRC_RELS = (
    "services/central/src",
    "services/fieldbus/src",
    "crates/openfdd_mqtt/src",
    "edge/src",
)

# Strict markers never exempt on "not pandas" prose. Broad Command token may.
FORBIDDEN_PRODUCT_RS = (
    # Denylist / policy strings may mention pandas; require no policy prose for hit.
    (re.compile(r"\bpandas\b", re.I), "policy_prose_ok"),
    (re.compile(r"""Command::new\(\s*["'](?:python3?|pip3?|streamlit)["']""", re.I), "strict"),
    (re.compile(r"""["'](?:python3?|pip3?)\s+-[cm]""", re.I), "strict"),
    (re.compile(r"std::process::Command", re.I), "policy_prose_ok"),
)

CLOSURE_REL = "docs/migration/react-rust/COMPUTATION_CLOSURE.md"


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


def check_product_compose(errors: list[str], root: Path = ROOT) -> None:
    for rel in PRODUCT_COMPOSE_REL:
        path = root / rel
        if not path.is_file():
            continue
        text = _strip_yaml_comments(path.read_text(encoding="utf-8"))
        for env in FORBIDDEN_ENV:
            if env in text:
                errors.append(f"{rel} must not set {env}")
        if path.name == "compose.react.yml":
            if re.search(r"(?m)^  ui:\s*$", text):
                errors.append("compose.react.yml must not define a legacy `ui` service")
            for pat in FORBIDDEN_COMPOSE_MARKERS:
                if pat.search(text):
                    errors.append(
                        f"{rel} must not reference forbidden UI marker {pat.pattern!r}"
                    )


def check_closure_ledger(errors: list[str], root: Path = ROOT) -> None:
    path = root / CLOSURE_REL
    if not path.is_file():
        errors.append(f"missing {CLOSURE_REL}")
        return
    text = path.read_text(encoding="utf-8")
    for needle in ("CLOSED", "ORACLE", "PROVISIONAL", "sql_screening"):
        if needle not in text:
            errors.append(f"COMPUTATION_CLOSURE.md missing required marker {needle!r}")


def _policy_prose(line: str) -> bool:
    return bool(
        re.search(
            r"\b(forbid|forbidden|ban|banned|never|not|reject|must not|policy|deny)\b",
            line,
            re.I,
        )
    )


def check_product_rust(errors: list[str], root: Path = ROOT) -> None:
    for rel_root in PRODUCT_SRC_RELS:
        src_root = root / rel_root
        if not src_root.is_dir():
            # Optional in synthetic self-test trees.
            continue
        for path in src_root.rglob("*.rs"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(f"unreadable {rel}: {exc}")
                continue
            for pat, mode in FORBIDDEN_PRODUCT_RS:
                for i, line in enumerate(text.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("//"):
                        continue
                    if not pat.search(line):
                        continue
                    if mode == "policy_prose_ok" and _policy_prose(line):
                        continue
                    errors.append(
                        f"{rel}:{i} matches forbidden runtime marker {pat.pattern!r}: {stripped}"
                    )


def collect_errors(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    check_product_compose(errors, root)
    check_closure_ledger(errors, root)
    check_product_rust(errors, root)
    return errors


def self_test() -> int:
    """Intentional fail fixtures — each must produce at least one error."""
    failures: list[str] = []

    # 1) Retired pandas FDD env in product compose.
    with tempfile.TemporaryDirectory(prefix="phase2-compose-") as tmp:
        root = Path(tmp)
        compose = root / "docker" / "compose.react.yml"
        compose.parent.mkdir(parents=True)
        compose.write_text(
            "services:\n  web:\n    environment:\n      OPENFDD_ALLOW_PANDAS_FDD: \"1\"\n",
            encoding="utf-8",
        )
        (root / CLOSURE_REL).parent.mkdir(parents=True)
        (root / CLOSURE_REL).write_text(
            "CLOSED ORACLE PROVISIONAL sql_screening\n", encoding="utf-8"
        )
        errs = collect_errors(root)
        if not any("OPENFDD_ALLOW_PANDAS_FDD" in e for e in errs):
            failures.append("compose pandas env fixture did not fail")

    # 2) Strict python spawn — "not pandas" prose must NOT exempt.
    with tempfile.TemporaryDirectory(prefix="phase2-py-") as tmp:
        root = Path(tmp)
        rs = root / "services" / "central" / "src" / "bad.rs"
        rs.parent.mkdir(parents=True)
        rs.write_text(
            '// not pandas — still forbidden\nlet _ = Command::new("python3");\n',
            encoding="utf-8",
        )
        (root / CLOSURE_REL).parent.mkdir(parents=True)
        (root / CLOSURE_REL).write_text(
            "CLOSED ORACLE PROVISIONAL sql_screening\n", encoding="utf-8"
        )
        errs = collect_errors(root)
        if not any("python3" in e for e in errs):
            failures.append("python Command::new fixture did not fail (strict)")

    # 3) Missing closure markers.
    with tempfile.TemporaryDirectory(prefix="phase2-closure-") as tmp:
        root = Path(tmp)
        (root / CLOSURE_REL).parent.mkdir(parents=True)
        (root / CLOSURE_REL).write_text("incomplete ledger\n", encoding="utf-8")
        errs = collect_errors(root)
        if not any("missing required marker" in e for e in errs):
            failures.append("incomplete closure fixture did not fail")

    if failures:
        print("phase2_computation_policy_check --self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("phase2_computation_policy_check --self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run intentional fail fixtures (must fail the gate).",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    errors = collect_errors(ROOT)
    if errors:
        print("phase2_computation_policy_check FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("phase2_computation_policy_check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
