"""Bundle model + rule YAML for OpenClaw; parse structured redesign response."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def collect_managed_rule_yaml_texts(rules_root: Path, *, max_bytes: int = 800_000) -> list[tuple[str, str]]:
    """Return (relative_path, utf8_text) for each *.yaml / *.yml under rules_root."""
    out: list[tuple[str, str]] = []
    total = 0
    if not rules_root.is_dir():
        return out
    for path in sorted(rules_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".yaml", ".yml"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(rules_root).as_posix()
        chunk = len(text.encode("utf-8"))
        if total + chunk > max_bytes:
            break
        total += chunk
        out.append((rel, text))
    return out


def build_data_model_redesign_user_message(model: dict[str, Any], rule_files: list[tuple[str, str]]) -> str:
    parts: list[str] = [
        "The following is the current GET /model/export JSON (data_model_export.json):",
        json.dumps(model, indent=2),
        "",
        "The following are all managed rule YAML files for this project:",
    ]
    for rel, body in rule_files:
        parts.append(f"--- FILE: {rel} ---")
        parts.append(body.rstrip())
        parts.append("")
    parts.append(
        "Both artifacts are present. Follow your system instructions: for this bridge call, respond with ONE valid "
        "JSON object containing at least validation_notes, relationship_summary, rule_compatibility_notes, "
        "and import_ready_json (sites/equipment/points only inside import_ready_json)."
    )
    return "\n".join(parts)


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_fence(text: str) -> str | None:
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else None


_FILE_SECTION_RE = re.compile(
    r"^===\s*FILE:\s*(?P<name>[^\n]+?)\s*===\s*\n(?P<body>[\s\S]*?)(?=^===\s*FILE:|\Z)",
    re.MULTILINE,
)


def _extract_import_from_copy_paste_sections(text: str) -> dict[str, Any] | None:
    """Parse === FILE: open_fdd_data_model_import_ready.json === ... blocks from LLM fallback format."""
    for m in _FILE_SECTION_RE.finditer(text):
        name = (m.group("name") or "").strip()
        body = (m.group("body") or "").strip()
        if not body:
            continue
        lower = name.lower()
        if not (
            "import_ready" in lower
            or lower.endswith(".json")
            or "data_model_import" in lower
        ):
            continue
        try:
            obj: Any = json.loads(body)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        sites = obj.get("sites")
        equipment = obj.get("equipment")
        points = obj.get("points")
        if isinstance(sites, list) and isinstance(equipment, list) and isinstance(points, list):
            return {"sites": sites, "equipment": equipment, "points": points}
    return None


def extract_import_shape_from_llm_output(content: str) -> dict[str, Any] | None:
    """
    Best-effort parse of LLM output into import payload {sites, equipment, points}.

    Accepts: bare import object; wrapper with import_ready_json / proposed_model_json;
    markdown-fenced JSON; or copy/paste ``=== FILE: ...import_ready...json ===`` sections.
    """
    raw = (content or "").strip()
    if not raw:
        return None
    candidates: list[str] = [raw]
    fenced = _extract_json_fence(raw)
    if fenced:
        candidates.append(fenced)
    for candidate in candidates:
        try:
            parsed: Any = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        ir = parsed.get("import_ready_json")
        if isinstance(ir, dict):
            parsed = ir
        elif isinstance(parsed.get("proposed_model_json"), dict):
            parsed = parsed["proposed_model_json"]
        sites = parsed.get("sites")
        equipment = parsed.get("equipment")
        points = parsed.get("points")
        if isinstance(sites, list) and isinstance(equipment, list) and isinstance(points, list):
            return {"sites": sites, "equipment": equipment, "points": points}
    return _extract_import_from_copy_paste_sections(raw)
