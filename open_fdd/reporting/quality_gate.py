"""Pre-emit report quality audit."""

from __future__ import annotations

import re
from typing import Any

from open_fdd.reporting.models import Classification, EngineeringFinding, ReportArtifacts

CLIENT_OK = {
    Classification.STRONGLY_SUPPORTED,
    Classification.PROBABLE,
    Classification.INCONCLUSIVE,
    Classification.DATA_QUALITY,
}

# Negations / soft-denials that mention replace but are not a fix action.
_ANTI_REPLACE = re.compile(
    r"\b(?:do\s+not|don't|dont|never|avoid|no\s+need\s+to|without)\s+"
    r"(?:\w+\s+){0,3}replac(?:e|ement)\b"
    r"|\breplac(?:e|ement)\b\s+(?:is\s+)?(?:not|unnecessary|unwarranted)\b",
    re.IGNORECASE,
)
# Proactive replace / replacement of equipment / instrumentation.
_PROACTIVE_REPLACE = re.compile(
    r"\breplac(?:e|ement)\b.{0,48}\b(?:equipment|sensor|actuator|damper|valve|transmitter|transducer)\b"
    r"|\b(?:equipment|sensor|actuator|damper|valve|transmitter|transducer)\b.{0,48}\breplac(?:e|ement)\b"
    r"|\breplacement\s+of\b",
    re.IGNORECASE,
)


def _has_proactive_replace(corrective: list[str] | None) -> bool:
    """True when corrective text recommends replacing hardware (not honesty language)."""
    for raw in corrective or []:
        text = str(raw or "").strip()
        if not text:
            continue
        # Drop negated clauses before matching proactive language.
        cleaned = _ANTI_REPLACE.sub(" ", text)
        if not re.search(r"replac", cleaned, re.IGNORECASE):
            continue
        if _PROACTIVE_REPLACE.search(cleaned):
            return True
        if re.search(r"\breplace\b", cleaned, re.IGNORECASE):
            return True
    return False


def run_quality_gate(
    artifacts: ReportArtifacts,
    *,
    allow_priority: int | None = None,
) -> dict[str, Any]:
    """Return {ok, errors, warnings}. Reject if critical errors.

    ``allow_priority`` (BUG-020): when set, authorizes up to that many included
    priority findings. Default remains 7 without an explicit raise.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Prefer explicit arg; else artifacts.metrics / assumptions flag from pipeline
    authorized = allow_priority
    if authorized is None:
        authorized = (artifacts.metrics or {}).get("allow_priority")
    try:
        authorized_n = int(authorized) if authorized is not None else None
    except (TypeError, ValueError):
        authorized_n = None

    findings = [f for f in artifacts.findings if f.include_in_report]
    if len(findings) > 7:
        if authorized_n is None or len(findings) > authorized_n:
            errors.append(
                f"More than 7 priority findings ({len(findings)}) without explicit raise"
            )

    for f in findings:
        cls = f.effective_classification
        if cls not in CLIENT_OK and cls != Classification.DATA_QUALITY:
            errors.append(f"{f.finding_id}: non-client classification in body: {cls.value}")
        if not f.evidence_bullets:
            errors.append(f"{f.finding_id}: high-priority finding has no supporting evidence")
        if cls in {Classification.STRONGLY_SUPPORTED, Classification.PROBABLE}:
            if f.chart_spec is None and f.chart_path is None:
                warnings.append(f"{f.finding_id}: chartable finding has no chart_spec")
        # BUG-022: never silent-skip day zoom after charts attach
        has_zoom = bool(getattr(f, "day_zoom_path", None))
        has_zoom_err = bool(getattr(f, "day_zoom_skip_reason", None) or getattr(f, "day_zoom_error", None))
        # Only enforce when chart pass has run (charts list non-empty or any finding has zoom fields set)
        zoom_pass_done = bool(artifacts.charts) or any(
            getattr(x, "day_zoom_path", None) or getattr(x, "day_zoom_skip_reason", None)
            for x in artifacts.findings
        )
        if zoom_pass_done and f.include_in_report and not has_zoom and not has_zoom_err:
            errors.append(f"{f.finding_id}: day-zoom missing path and error (silent skip)")
        title_l = f.title.lower()
        if "comfort" in title_l and cls != Classification.DATA_QUALITY:
            # dead sensor comfort
            if any("implausible" in (b or "").lower() or "instrumentation" in (b or "").lower() for b in f.evidence_bullets):
                errors.append(f"{f.finding_id}: dead/impossible sensor described as comfort problem")
        if _has_proactive_replace(f.possible_corrective) and cls not in {
            Classification.STRONGLY_SUPPORTED,
            Classification.PROBABLE,
        }:
            errors.append(f"{f.finding_id}: 'replace' recommendation without sufficient evidence class")
        # Near-100% confirmed without common-mode note
        score = float(f.automated_assessment.get("score") or 0)
        if cls == Classification.STRONGLY_SUPPORTED and f.automated_assessment.get("common_mode_review"):
            if not any("common" in r.lower() or "near" in r.lower() for r in (f.data_confidence_notes or [])):
                warnings.append(f"{f.finding_id}: strongly supported + common_mode — ensure skepticism documented")

    if not artifacts.analysis_period:
        warnings.append("Analysis period missing")
    if not artifacts.disclaimer:
        errors.append("Educational disclaimer missing")

    # FP mixed into findings
    for f in findings:
        if f.effective_classification == Classification.LIKELY_FALSE_POSITIVE:
            errors.append(f"{f.finding_id}: likely false positive mixed into client findings")

    ok = len(errors) == 0
    return {"ok": ok, "errors": errors, "warnings": warnings}
