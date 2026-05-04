"""Hard-coded SIMPLE vs COMPLEX routing for the built-in Open-FDD Codex agent (OpenClaw-inspired).

Classify the human task first, then choose reasoning depth and timeout hints — never burn a
"thinking-style" turn on work that fits SIMPLE unless the text clearly needs deeper analysis.
"""

from __future__ import annotations

import re
from typing import Literal

TaskTier = Literal["simple", "complex"]

# COMPLEX: ambiguous, cross-cutting, security/perf, multi-asset FDD, modeling redesigns.
_COMPLEX_PATTERNS: list[tuple[str, str]] = [
    (r"\brace condition\b", "race / timing"),
    (r"\btiming[- ]dependent\b", "timing-dependent"),
    (r"\bsecurity\b|\bvulnerab", "security"),
    (r"\bperformance\b|\bdegradation\b", "performance"),
    (r"\bambiguous\b|\broot cause\b", "ambiguous / root cause"),
    (r"\b(span|spans)\b.{0,40}\b(component|file|service|subsystem)", "multi-component"),
    (r"\b(multi[- ]site|cross[- ]site|all sites)\b", "multi-site"),
    (r"\b(brick|sparql|ttl)\b.{0,40}\b(import|export|merge|refactor)", "BRICK/SPARQL/TTL redesign"),
    (r"\brule pack\b.{0,40}\b(redesign|overhaul|architecture)", "rule architecture"),
    (r"\bingest\b.{0,40}\b(pipeline|architecture|redesign)", "ingest architecture"),
    (r"\bunexpected\b.{0,40}\b(pass|passed)\b", "unexpected pass"),
]

# SIMPLE: direct checks, single-file/single-endpoint, obvious errors, trivial scripts.
_SIMPLE_PATTERNS: list[tuple[str, str]] = [
    (r"\bpass/fail\b", "pass/fail"),
    (r"\bhttp\b.{0,30}\b(404|500|502|503|timeout)\b", "HTTP status / timeout"),
    (r"\bmissing\b.{0,30}\b(ui|selector|element)\b", "missing UI"),
    (r"\bsetup failure\b|\benv(ironment)?\b.{0,20}\b(wrong|missing)\b", "setup / env"),
    (r"\bsyntax error\b|\bimport failure\b|\bmodulenotfound", "syntax / import"),
    (r"\b(get|post)\s+/\s*health\b|\b/health\b", "health check"),
    (r"\blist sites\b|\bget\s+/sites\b", "list sites"),
    (r"\bsingle (csv|file|column)\b", "single artifact"),
    (r"\b(one[- ]liner|quick check|trivial)\b", "explicitly trivial"),
]


def classify_openfdd_task(task_summary: str, *, default: TaskTier = "simple") -> tuple[TaskTier, str]:
    """
    Default SIMPLE unless text matches COMPLEX, or matches SIMPLE explicitly.

    If both match, COMPLEX wins (safer).
    """
    text = str(task_summary or "").strip().lower()
    if not text:
        return default, "empty summary -> default tier"

    complex_hits: list[str] = []
    for pattern, label in _COMPLEX_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            complex_hits.append(label)
    if complex_hits:
        return "complex", "complex signals: " + ", ".join(complex_hits[:4])

    for pattern, label in _SIMPLE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "simple", f"simple signal: {label}"

    return default, "no specific pattern -> default tier"


def routing_instructions_for_tier(tier: TaskTier) -> str:
    if tier == "simple":
        return (
            "## Routing mode: SIMPLE (primary)\n"
            "- Answer directly; prefer the smallest change or one bridge/MCP call.\n"
            "- Use short plans (3–7 bullets max) unless the human asked for detail.\n"
            "- Do not spin a long investigation unless the request clearly needs it.\n"
        )
    return (
        "## Routing mode: COMPLEX (thinking-style)\n"
        "- Outline hypotheses, then narrow with evidence (logs, API JSON, file excerpts).\n"
        "- Call out tradeoffs, risks, and rollback for data / rules / ingest changes.\n"
        "- If multiple subsystems touch (rules + ingest + plots), sequence work safely.\n"
    )
