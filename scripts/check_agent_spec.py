#!/usr/bin/env python3
"""Fail when AGENTS.md or openfdd_agent_spec/ names a missing path, command or rule id.

Also requires the spec to quote the live roles version, UI API contract version, SQL rule
count and DuckDB floor, which are read from the repo rather than hard-coded here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_GLOBS = ("AGENTS.md", "openfdd_agent_spec/**/*.md")
FENCE = re.compile(r"^(```|~~~)(.*)$")
TICK = re.compile(r"`([^`\n]+)`")
RULE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
CMD = re.compile(r"\b(?:python3|node|pytest)\s+([^\n;&|]+)")
ROOT_PREFIXES = (
    "nf-app/", "lite/", "sql/", "scripts/", "docs/", "open_fdd/", "openfdd_agent_spec/",
    "tools/", "deploy/", "roles/", "contract/", "openapi/", "tests/", ".github/",
    ".agents/", ".claude/", "shared/", "static/", "hooks/",
)
FORBIDDEN = (
    "cerl", "usace", "mody", "iroc", "slipstream", "blackstone", "kangasys", "phrc", "simplesense",
)
# "bps" is a short token; match it as a whole word only.
FORBIDDEN_WORDS = ("bps",)
SKIP_PREFIXES = ("http://", "https://", "mailto:", "~", "$", "#", "/", "@")


def spec_files(root: Path) -> list[Path]:
    files = []
    for pattern in SPEC_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    return [p for p in files if p.is_file()]


def spec_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in spec_files(root))


def _iter_lines(text: str):
    """Yield (fenced, lang, line). Fence markers themselves are skipped."""
    fenced = False
    lang = ""
    for line in text.splitlines():
        marker = FENCE.match(line.strip())
        if marker:
            if not fenced:
                fenced = True
                lang = marker.group(2).strip().lower()
            else:
                fenced = False
                lang = ""
            continue
        yield fenced, lang, line


def _prose(text: str) -> str:
    return "\n".join(line for fenced, _lang, line in _iter_lines(text) if not fenced)


def _is_repo_path(token: str) -> bool:
    if any(c in token for c in " \t()<>'\"=,|") or token.startswith(SKIP_PREFIXES):
        return False
    if token.startswith("--") or "://" in token:
        return False
    return token.startswith(ROOT_PREFIXES)


def _resolve(root: Path, token: str) -> bool:
    bases = (root, root / "nf-app", root / "lite")
    if any(c in token for c in "*?["):
        return any(any(base.glob(token)) for base in bases)
    return any((base / token).exists() for base in bases)


def _path_tokens(text: str) -> list[str]:
    tokens = []
    for fenced, lang, line in _iter_lines(text):
        if not fenced:
            for raw in TICK.findall(line):
                tokens.append(raw.strip().strip(".,:;"))
        if (not fenced) or lang in ("bash", "sh", "shell", ""):
            for match in CMD.finditer(line):
                for part in match.group(1).split():
                    if part.startswith("-"):
                        continue
                    tokens.append(part.strip("`.,:;"))
    return tokens


def path_errors(text: str, root: Path) -> list[str]:
    errors = []
    seen = set()
    for token in _path_tokens(text):
        if not _is_repo_path(token) or token in seen:
            continue
        seen.add(token)
        if not _resolve(root, token):
            errors.append(f"missing path `{token}`")
    return errors


def _quoted_in_code(root: Path, token: str) -> bool:
    needle_dq = f'"{token}"'
    needle_sq = f"'{token}'"
    for folder in ("nf-app", "sql", "open_fdd", "shared", "scripts"):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in {".js", ".mjs", ".py", ".sql", ".json", ".yaml", ".yml"}:
                continue
            if "node_modules" in path.parts or path.name.startswith("pack-"):
                continue
            try:
                blob = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if needle_dq in blob or needle_sq in blob:
                return True
    return False


def rule_id_errors(text: str, ids: set[str], root: Path | None = None) -> list[str]:
    errors = []
    seen = set()
    for raw in TICK.findall(_prose(text)):
        token = raw.strip()
        if not RULE_ID.fullmatch(token) or token in ids or token in seen:
            continue
        seen.add(token)
        if root is not None and _quoted_in_code(root, token):
            continue
        errors.append(f"unknown rule id `{token}`")
    return errors


def _load_json(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def fact_errors(root: Path, text: str) -> list[str]:
    errors = []
    roles = _load_json(root, "roles/openfdd-roles.json")
    catalog = _load_json(root, "nf-app/static/fdd-catalog.json")
    pkg = _load_json(root, "nf-app/package.json")
    openapi = (root / "openapi/open-fdd-ui-api.yaml").read_text(encoding="utf-8")
    version_match = re.search(r"(?m)^  version:\s*(\S+)\s*$", openapi)
    contract_version = version_match.group(1) if version_match else ""
    duck_py = "duckdb>=2.0.1"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if duck_py not in pyproject:
        errors.append(f"pyproject.toml no longer contains {duck_py}; update the spec and this check together")
    duck_npm = pkg.get("optionalDependencies", {}).get("@duckdb/node-api", "")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    contract = (root / "openfdd_agent_spec/DATA_CONTRACT.md").read_text(encoding="utf-8")
    architecture = (root / "openfdd_agent_spec/ARCHITECTURE.md").read_text(encoding="utf-8")
    n = len(catalog["rules"])
    required = {
        "AGENTS.md": (
            f"{n} SQL rules",
            roles["version"],
            "duckdb>=2.0.1",
            duck_npm,
            "parity-stress.yml",
            "bbartling",
            "do not map or poll every point",
            "do not write a controller station",
        ),
        "DATA_CONTRACT.md": (
            roles["version"],
            contract_version,
            "DEG_C",
            "active_hours",
            "covered_hours",
            "no_run_proof",
            "SV-STALE",
            "SV-FLATLINE",
            "confirm_min",
            "not in this tree",
        ),
        "ARCHITECTURE.md": (
            "METRIC",
            "active_hours",
            "ECharts",
            "sqlite",
            "pglite",
            "duckdb",
            "timescale",
            "sql/analytics",
            "Node 22",
        ),
    }
    blobs = {"AGENTS.md": agents, "DATA_CONTRACT.md": contract, "ARCHITECTURE.md": architecture}
    for name, phrases in required.items():
        for phrase in phrases:
            if phrase and phrase not in blobs[name]:
                errors.append(f"{name} must mention {phrase!r}")
    low = text.lower()
    for word in FORBIDDEN:
        if re.search(rf"\b{re.escape(word)}\b", low):
            errors.append(f"forbidden name {word}")
    for word in FORBIDDEN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", low):
            errors.append(f"forbidden name {word}")
    if "Grok Bot" in text:
        errors.append("spec still names Grok Bot as the deployer")
    if "5.0.3 app" in text:
        errors.append("spec still describes the 5.0.3 analytics app")
    return errors


def check(root: Path) -> list[str]:
    files = spec_files(root)
    if not files:
        return ["no agent spec files"]
    text = spec_text(root)
    catalog = _load_json(root, "nf-app/static/fdd-catalog.json")
    ids = {rule["id"] for rule in catalog["rules"]}
    errors = path_errors(text, root) + rule_id_errors(text, ids, root) + fact_errors(root, text)
    return errors


def main() -> int:
    errors = check(ROOT)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"agent spec checked ({len(spec_files(ROOT))} files)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
