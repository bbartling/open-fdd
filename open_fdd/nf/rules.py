"""Run the pandas reference rules (``open_fdd.rules``) on NF equipment frames.

The frames come from ``open_fdd.nf.model.equipment_frames`` (SI, role-named columns). The rules
own all gating (operational proof, occupancy, missing roles); this module only runs them and
tidies the result. An unknown is never healthy: a rule that was not assessed (missing roles,
equipment never proven on, no covered samples) is reported ``not-assessed``, never ``ok``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

COLUMNS = ["site", "equip", "rule", "status", "fault_hours", "fault_pct", "coverage",
           "raw_status", "missing_roles", "notes"]


def rule_results(
    frames: Mapping[tuple[str, str], Any],
    rules: Iterable[str] | None = None,
    params_by_rule: dict[str, dict] | None = None,
    require_operational_gates: bool = True,
) -> list[tuple[str, str, Any]]:
    """``[(site, equip, RuleResult), ...]`` for every applicable rule (not-applicable ones dropped)."""
    from open_fdd.rules.runner import run_all_cookbook_rules

    want = {r.upper() for r in rules} if rules else None
    out = []
    for (site, equip), df in frames.items():
        poll = float(df.attrs.get("window_sec") or 300)
        results = run_all_cookbook_rules(
            df, equipment_id=equip, poll_seconds=poll, params_by_rule=params_by_rule,
            site_id=site, equipment_type=str(df.attrs.get("equipment_type") or ""),
            require_operational_gates=require_operational_gates,
        )
        for res in results:
            if res.status == "NOT_APPLICABLE_EQUIPMENT_TYPE":
                continue
            if want and res.rule_id.upper() not in want:
                continue
            out.append((site, equip, res))
    return out


def _tidy_status(res: Any) -> tuple[str, float | None]:
    """(status, coverage): ok | fault | not-assessed | error; coverage = assessed share of the frame."""
    if res.status == "ERROR":
        return "error", None
    if res.status not in ("PASS", "FAULT"):
        return "not-assessed", 0.0
    total = float(res.metrics.get("total_sample_count") or 0)
    active = float(res.metrics.get("active_sample_count") or 0)
    coverage = (active / total) if total else 0.0
    if coverage <= 0.0:
        return "not-assessed", 0.0
    return ("fault" if res.status == "FAULT" else "ok"), round(coverage, 4)


def results_table(results):
    """Tidy DataFrame from ``rule_results`` output."""
    import pandas as pd

    rows: list[dict[str, Any]] = []
    for site, equip, res in results:
        status, cov = _tidy_status(res)
        assessed = status in ("ok", "fault")
        rows.append({
            "site": site, "equip": equip, "rule": res.rule_id, "status": status,
            "fault_hours": res.fault_hours if assessed else None,
            "fault_pct": res.fault_pct if assessed else None,
            "coverage": cov, "raw_status": res.status,
            "missing_roles": ",".join(res.missing_roles), "notes": res.notes,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def run_rules(
    frames: Mapping[tuple[str, str], Any],
    rules: Iterable[str] | None = None,
    params_by_rule: dict[str, dict] | None = None,
    require_operational_gates: bool = True,
):
    """Tidy DataFrame ``(site, equip, rule, status, fault_hours, fault_pct, coverage, ...)``.

    ``status`` is ``ok``, ``fault``, ``not-assessed`` or ``error``. ``fault_hours`` / ``fault_pct``
    are filled only for assessed rules (``fault_pct`` is the share of the rule's active hours).
    ``raw_status`` keeps the rule's own status (PASS, FAULT, SKIPPED_MISSING_ROLES, ...).
    """
    return results_table(rule_results(frames, rules, params_by_rule, require_operational_gates))
