"""The existing pandas rule pack as an FDD baseline: per-sample union of confirmed faults across AHU rules.

Rules run exactly as the parity reference runs them (``open_fdd.parity.pandas_ref.pandas_rule_result``: operational
gates on, the pack's ``confirm_min`` persistence). A rule that skips (missing roles) contributes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


def ahu_rule_ids() -> list[str]:
    from open_fdd.rules import RULES_BY_ID

    return list(dict.fromkeys(r.id for r in RULES_BY_ID.values() if "ahu" in (r.equipment_kinds or [])))


@dataclass
class RulePackRun:
    flags: dict[str, pd.Series] = field(default_factory=dict)  # rule id -> confirmed fault on the frame index
    status: dict[str, str] = field(default_factory=dict)

    def union(self, index: pd.Index, rules: list[str] | None = None) -> pd.Series:
        out = pd.Series(False, index=index)
        for rule, mask in self.flags.items():
            if rules is not None and rule not in rules:
                continue
            out |= mask.reindex(index).fillna(False).astype(bool)
        return out


def run_rule_pack(frame: pd.DataFrame, *, poll_seconds: float = 300.0, rules: list[str] | None = None) -> RulePackRun:
    """Run every AHU rule (or ``rules``) on one SI role frame; keep each rule's confirmed-fault mask."""
    import copy

    from open_fdd.parity.pandas_ref import pandas_rule_result

    run = RulePackRun()
    frame = frame.copy()
    frame.attrs.setdefault("equipment_id", "AHU-1")
    frame.attrs.setdefault("role_units", {})
    for rule in rules or ahu_rule_ids():
        df = frame.copy()
        df.attrs = copy.deepcopy(frame.attrs)
        try:
            _hours, status, res = pandas_rule_result(rule, df, None, poll_seconds)
        except Exception as exc:  # noqa: BLE001 - a broken rule is reported, never hidden
            run.status[rule] = f"ERROR {type(exc).__name__}: {exc}"
            continue
        run.status[rule] = str(status)
        mask = getattr(res, "confirmed_fault", None) if res is not None else None
        if mask is not None and status == "FAULT":
            run.flags[rule] = mask.reindex(frame.index).fillna(False).astype(bool)
    return run
