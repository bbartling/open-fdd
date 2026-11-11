"""No-name-heuristics guard: plot selection reads the model, never point names.

The two producers (Python and JS) may not contain point-name regexes, name or key maps, or substring tests on names.
The allowlists below are the only exceptions: rule-id family patterns (rule ids are part of the contract) and
canonical constants.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "open_fdd" / "plot_spec.py"
JS = ROOT / "nf-app" / "static" / "plot-spec.js"

# Regex sources allowed in the producers: rule-id families, and the window / unit text normalisers.
ALLOWED_REGEX = {
    r"^SV-(RATE|RANGE|FLATLINE|SPIKE|STALE)$",
    r"^ECON-[1-7]$",
    r"(Z|[+-]\d{2}:?\d{2})$",     # JS: does a window time carry a zone
    r"[\s_]",                     # JS: unit-spelling normaliser (same as units.js)
}
# Module-level names allowed to be dict/set/list literals of strings: canonical constants only.
ALLOWED_CONSTANTS = {"GENERIC_MARKERS", "__all__", "SWEEP_RULE_PATTERN", "ECON_RULE_PATTERN"}
# Names of the old per-app heuristics; they must not come back.
FORBIDDEN_IDENTIFIERS = [
    "ROLE_TO_KEYS", "RULE_PLOT_KEYS", "_PREFERRED_HAYSTACK", "DEFAULT_KEY_TO_COL", "SENSOR_ROLES", "SENSOR_LIMITS",
    "_SV_ROLE_PRIORITY", "_PID_ROLE_PRIORITY", "SITEWIDE_ROLES", "RULE_EQUIP_TAG", "OVERLAY_FOR", "FAMILY_OF_QUANTITY",
    "seriesLooksLike", "temperatureKey", "unitFamily", "semanticsForRole",
]


def _py_tree() -> ast.Module:
    return ast.parse(PY.read_text(encoding="utf-8"))


def test_python_producer_has_no_name_regexes_or_maps():
    tree = _py_tree()
    patterns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "re":
            arg = node.args[0]
            if isinstance(arg, ast.Constant):
                patterns.append(arg.value)
            else:
                assert isinstance(arg, ast.Name) and arg.id in ALLOWED_CONSTANTS, "re.* takes a literal or an allowlisted constant"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "fnmatch":
            raise AssertionError("fnmatch on names is not allowed")
    # the compiled patterns are built from the allowlisted constants; check the constants' text
    consts = {n.targets[0].id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
    sources = {consts[k] for k in ("SWEEP_RULE_PATTERN", "ECON_RULE_PATTERN")} | {p for p in patterns if isinstance(p, str)}
    assert sources <= ALLOWED_REGEX, sources - ALLOWED_REGEX
    # no module-level dict or set literal of strings except the allowlisted canonical constants
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if isinstance(node.value, (ast.Dict, ast.Set)) and name not in ALLOWED_CONSTANTS:
                raise AssertionError(f"module-level map {name}: selection must come from the model and the registry")
    text = PY.read_text(encoding="utf-8")
    for bad in FORBIDDEN_IDENTIFIERS:
        assert bad not in text, bad


def _strip_js(source: str) -> str:
    """JS with comments and string/template contents blanked (so only code remains), regex literals kept."""
    out, i, n = [], 0, len(source)
    while i < n:
        c = source[i]
        if source.startswith("//", i):
            while i < n and source[i] != "\n":
                i += 1
        elif source.startswith("/*", i):
            i = source.index("*/", i) + 2
        elif c in "'\"`":
            q = c
            i += 1
            while source[i] != q:
                i += 2 if source[i] == "\\" else 1
            i += 1
            out.append(q + q)
        else:
            out.append(c)
            i += 1
    return "".join(out)


def test_js_producer_has_no_name_regexes_or_maps():
    raw = JS.read_text(encoding="utf-8")
    code = _strip_js(raw)
    # regex literals: a slash after one of ( = : , ! & | ? { } ; [ or start of line, not a comment
    found = []
    for m in re.finditer(r"(?:^|[(=:,!&|?{};\[])\s*(/(?![/*])(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+/[a-z]*)", code, re.M):
        found.append(m.group(1))
    bodies = {re.sub(r"/[a-z]*$", "", f)[1:] for f in found}
    assert bodies, "expected the rule-id family patterns"
    assert bodies <= {a for a in ALLOWED_REGEX}, bodies - ALLOWED_REGEX
    assert "new RegExp" not in code
    for bad in FORBIDDEN_IDENTIFIERS:
        assert bad not in raw, bad
    # no top-level object-literal maps of names: every const object literal at the top of the IIFE must be allowlisted
    for m in re.finditer(r"^  const (\w+) = \{", code, re.M):
        if m.group(1) != "api":      # the export object
            raise AssertionError(f"module-level map {m.group(1)} in plot-spec.js")


def test_no_substring_tests_on_names_in_either_producer():
    # selection compares markers, classes and units, never `name`/`dis` text
    for path in (PY, JS):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(dis|name)\s*(\.|\[)\s*(includes|startswith|startsWith|endswith|endsWith|match|search|test)\b", text, re.I), path.name
        assert not re.search(r"\b(includes|startswith|startsWith)\(\s*['\"](temp|supply|discharge|zone|oa|sat|mat)\b", text, re.I), path.name
