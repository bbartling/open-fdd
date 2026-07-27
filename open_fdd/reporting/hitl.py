"""HITL pin / drop / note overrides for Engineering Findings (BUG-021)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_fdd.reporting.models import (
    CandidateDetection,
    Classification,
    EngineeringFinding,
    FindingAssessment,
)


def normalize_finding_ref(raw: str) -> str:
    """Accept ``equipment|rule``, ``equipment:rule``, or bare finding_id / equipment."""
    s = (raw or "").strip()
    if not s:
        return ""
    if ":" in s and "|" not in s:
        left, right = s.split(":", 1)
        return f"{left.strip()}|{right.strip()}"
    return s


def parse_note_arg(raw: str) -> tuple[str, str]:
    """``id=text`` → (ref, note)."""
    s = (raw or "").strip()
    if "=" not in s:
        raise ValueError(f"Note must be id=text, got: {raw!r}")
    left, right = s.split("=", 1)
    return normalize_finding_ref(left), right.strip()


def load_notes_file(path: Path | str | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Notes file must be a JSON object of ref → note")
    return {normalize_finding_ref(str(k)): str(v) for k, v in data.items()}


def _refs_match_finding(ref: str, f: EngineeringFinding) -> bool:
    if not ref:
        return False
    if ref == f.finding_id:
        return True
    keys = list(f.candidate_keys or [])
    if ref in keys:
        return True
    if "|" in ref:
        # Exact equipment|rule membership only (avoid cluster cross-product false hits)
        return ref in keys
    # bare equipment id
    return ref in (f.equipment_ids or [])


def _refs_match_candidate(ref: str, c: CandidateDetection) -> bool:
    if not ref:
        return False
    if ref == c.key or ref == c.equipment_id:
        return True
    if "|" in ref:
        eid, rid = ref.split("|", 1)
        return c.equipment_id == eid and c.rule_id == rid
    return False


def apply_hitl_overrides(
    findings: list[EngineeringFinding],
    *,
    pin_refs: list[str] | None = None,
    drop_refs: list[str] | None = None,
    notes: dict[str, str] | None = None,
    candidates: list[CandidateDetection] | None = None,
    assessments: dict[str, FindingAssessment] | None = None,
    suppressed: list[dict[str, Any]] | None = None,
) -> list[EngineeringFinding]:
    """Apply pin / drop / notes. Pins force ``include_in_report`` and may promote orphans."""
    pins = [normalize_finding_ref(x) for x in (pin_refs or []) if x]
    drops = [normalize_finding_ref(x) for x in (drop_refs or []) if x]
    note_map = {normalize_finding_ref(k): v for k, v in (notes or {}).items()}
    out = list(findings)
    by_key = {c.key: c for c in (candidates or [])}
    assessments = assessments or {}

    # Promote pinned candidates missing from priority pack
    existing_keys = {k for f in out for k in (f.candidate_keys or [])}
    for ref in pins:
        if any(_refs_match_finding(ref, f) for f in out):
            continue
        cand = None
        if ref in by_key:
            cand = by_key[ref]
        else:
            for c in by_key.values():
                if _refs_match_candidate(ref, c):
                    cand = c
                    break
        if cand is None:
            continue
        if cand.key in existing_keys:
            continue
        a = assessments.get(cand.key)
        score = float(a.score) if a else float(cand.fault_hours or 0)
        cls = a.classification if a else Classification.PROBABLE
        fid = f"PIN{len(out)+1:02d}"
        title = f"{cand.equipment_id} · {cand.rule_id} (pinned)"
        promoted = EngineeringFinding(
            finding_id=fid,
            title=title,
            classification=cls,
            priority=len(out) + 1,
            why_it_matters="Pinned by engineer / agent for field follow-up.",
            observed_behavior=cand.notes or f"FAULT hours≈{cand.fault_hours}",
            evidence_bullets=(a.supporting[:4] if a and a.supporting else [f"Pinned candidate {cand.key}"]),
            contradicting_evidence=(a.contradicting[:2] if a else []) or ["None material in automated review"],
            likely_causes=(a.likely_causes[:3] if a else []) or ["Verify in field"],
            field_verification=(a.field_verification[:3] if a else []) or [f"Inspect {cand.equipment_id}"],
            possible_corrective=["Do not replace equipment solely from this telemetry review — complete field verification first"],
            rule_ids=[cand.rule_id],
            equipment_ids=[cand.equipment_id],
            systems=[_guess_system(cand)],
            candidate_keys=[cand.key],
            automated_assessment=(a.to_dict() if a else {"score": score, "pinned": True}),
            include_in_report=True,
            data_confidence_notes=["Pinned via --pin-finding / HITL"],
            engineer_override={"pinned": True, "automated_classification": cls.value},
        )
        out.append(promoted)
        existing_keys.add(cand.key)
        if suppressed is not None:
            suppressed[:] = [
                row
                for row in suppressed
                if cand.key not in str(row.get("candidate_key") or "")
            ]

    for f in out:
        if any(_refs_match_finding(ref, f) for ref in pins):
            f.include_in_report = True
            ov = dict(f.engineer_override or {})
            ov["pinned"] = True
            f.engineer_override = ov
        if any(_refs_match_finding(ref, f) for ref in drops):
            f.include_in_report = False
            ov = dict(f.engineer_override or {})
            ov["dropped"] = True
            f.engineer_override = ov
        for ref, text in note_map.items():
            if _refs_match_finding(ref, f) and text:
                ov = dict(f.engineer_override or {})
                ov["note"] = text
                ov.setdefault("automated_classification", f.classification.value)
                f.engineer_override = ov

    # Re-number included priority slots for stable F01…
    included = [f for f in out if f.include_in_report]
    for i, f in enumerate(included, 1):
        f.priority = i
        if not str(f.finding_id).startswith("PIN"):
            f.finding_id = f"F{i:02d}"
    return out


def _guess_system(c: CandidateDetection) -> str:
    from open_fdd.reporting.scope import equipment_system

    return equipment_system(c.equipment_type, c.rule_id)
