"""Scope filters for Engineering Findings prioritization (BUG-019)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from open_fdd.reporting.models import CandidateDetection, EngineeringFinding

# Prefer terminal/zone FAULTs over plant when ``boost_terminal`` is set (BUG-019).
# Added to the evidence score for sort only — does not change stored assessment scores.
TERMINAL_SCORE_BOOST = 8.0


def equipment_system(equipment_type: str, rule_id: str) -> str:
    """AHU / CHW / HW / VAV / HP / Other — shared with findings clustering.

    RTU maps to AHU; heatPump / HP map to HP (dashboard contract).
    """
    et = (equipment_type or "").upper().replace(" ", "")
    if "AHU" in et or "RTU" in et or rule_id.startswith("SCHED") or rule_id == "FAN-OFF-STATIC":
        return "AHU"
    if "HEATPUMP" in et or et == "HP" or et.endswith("HP"):
        return "HP"
    if "CHILL" in et or rule_id.startswith("CHW"):
        return "CHW"
    if "BOIL" in et or rule_id.startswith("HW"):
        return "HW"
    if "VAV" in et or rule_id.startswith("VAV") or rule_id.startswith("SV-"):
        return "VAV"
    return et or "Other"


@dataclass
class FindingScope:
    """Optional filters applied before ranking (empty = no constraint on that axis)."""

    systems: list[str] = field(default_factory=list)
    equipment_prefixes: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    boost_terminal: bool = False

    @property
    def active(self) -> bool:
        return bool(self.systems or self.equipment_prefixes or self.rule_ids or self.boost_terminal)

    @classmethod
    def from_cli(
        cls,
        *,
        systems: str | None = None,
        equipment_prefix: str | None = None,
        rule_ids: str | None = None,
        boost_terminal: bool = False,
    ) -> FindingScope:
        return cls(
            systems=[s.upper() for s in _split_csv(systems)],
            equipment_prefixes=_split_csv(equipment_prefix),
            rule_ids=_split_csv(rule_ids),
            boost_terminal=bool(boost_terminal),
        )


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def parse_systems(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [s.upper() for s in _split_csv(raw)]
    return [str(s).strip().upper() for s in raw if str(s).strip()]


def candidate_matches_scope(c: CandidateDetection, scope: FindingScope | None) -> bool:
    """True when candidate passes all non-empty scope dimensions (AND)."""
    if scope is None:
        return True
    systems = [s.upper() for s in scope.systems]
    prefixes = list(scope.equipment_prefixes)
    rule_ids = set(scope.rule_ids)
    if not systems and not prefixes and not rule_ids:
        return True
    if systems:
        sys = equipment_system(c.equipment_type, c.rule_id).upper()
        if sys not in systems:
            return False
    if prefixes:
        eid = (c.equipment_id or "").upper()
        if not any(eid.startswith(p.upper()) for p in prefixes):
            return False
    if rule_ids and c.rule_id not in rule_ids:
        return False
    return True


def filter_candidates(
    candidates: list[CandidateDetection],
    scope: FindingScope | None,
) -> list[CandidateDetection]:
    if scope is None or not (scope.systems or scope.equipment_prefixes or scope.rule_ids):
        return list(candidates)
    return [c for c in candidates if candidate_matches_scope(c, scope)]


def is_terminal_finding(f: EngineeringFinding) -> bool:
    systems = {s.upper() for s in (f.systems or [])}
    if "VAV" in systems:
        return True
    if any((eid or "").upper().startswith("VAV") for eid in (f.equipment_ids or [])):
        return True
    if any((rid or "").upper().startswith("VAV") or (rid or "").upper().startswith("SV-") for rid in (f.rule_ids or [])):
        return True
    return False


def sort_key_for_finding(
    f: EngineeringFinding,
    *,
    boost_terminal: bool = False,
    cls_rank_fn=None,
) -> tuple:
    from open_fdd.reporting.models import Classification

    order = {
        Classification.STRONGLY_SUPPORTED: 5,
        Classification.PROBABLE: 4,
        Classification.DATA_QUALITY: 3,
        Classification.INCONCLUSIVE: 2,
        Classification.LIKELY_FALSE_POSITIVE: 1,
        Classification.NOT_ACTIONABLE: 0,
    }
    rank_fn = cls_rank_fn or (lambda c: order.get(c, 0))
    score = float((f.automated_assessment or {}).get("score") or 0)
    if boost_terminal and is_terminal_finding(f):
        score += TERMINAL_SCORE_BOOST
    return (-rank_fn(f.classification), -score)


def scope_to_dict(scope: FindingScope | None) -> dict[str, Any]:
    if scope is None:
        return {}
    return {
        "systems": list(scope.systems),
        "equipment_prefixes": list(scope.equipment_prefixes),
        "rule_ids": list(scope.rule_ids),
        "boost_terminal": bool(scope.boost_terminal),
        "terminal_score_boost": TERMINAL_SCORE_BOOST if scope.boost_terminal else 0.0,
    }
