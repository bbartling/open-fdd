"""The one compare policy: tolerance, fail on zero comparisons, fail on unexpected divergence, one-line verdict.

``compare(sql_rows, ref_rows, policy)`` takes

* ``sql_rows``: ``{rule_id: [row, ...]}`` as an engine adapter returns it (the contract output columns of the rule,
  e.g. ``equipment_id``, ``fault_hours``; per-sensor sweep rules also ``series_id``, ``sensor_role``, ``covered_hours``);
* ``ref_rows``: ``{rule_id: {equipment_id: {"pandas": hours | None, "status": str, ...}}}`` from ``reference()``.

A rule is *compared* when the reference has a twin for it and the engine returned a non-null ``fault_hours`` for at
least one equipment. A rule *matches* when every equipment agrees within the policy tolerance. A rule that does not
match is *known* when the policy lists it, otherwise *unexpected*.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Scopes of an entry in parity_known_differences.json.
SCOPES = ("all", "stress_only", "edge")


def known_differences(*scopes: str) -> dict[str, str]:
    """``{rule: reason}`` of the shipped known-difference list for the given scopes (default: ``all``)."""
    wanted = set(scopes or ("all",))
    bad = wanted - set(SCOPES)
    if bad:
        raise ValueError(f"unknown scope(s) {sorted(bad)}; expected {SCOPES}")
    doc = json.loads((DATA_DIR / "parity_known_differences.json").read_text(encoding="utf-8"))
    return {d["rule"]: d["reason"] for d in doc["differences"] if d["scope"] in wanted}


@dataclass(frozen=True)
class Policy:
    """Tolerances and the rules allowed to differ.

    ``abs_tol_h``: fault hours must agree within this many hours (both sides integrate forward sample holds on the
    same grid, so equal rules agree to floating-point noise). Per-sensor sweep rules compare per-role hours that the
    pandas oracle reports rounded to 0.001 h: ``sensor_abs_tol_h`` + ``sensor_rel_tol``.
    """

    known: Mapping[str, str] = field(default_factory=dict)
    abs_tol_h: float = 1e-6
    sensor_abs_tol_h: float = 0.0005
    sensor_rel_tol: float = 1e-6
    require_all_twins: bool = True

    @classmethod
    def default(cls, profile: str = "basic", stress: bool = True, **overrides) -> "Policy":
        """The shipped policy. ``stress`` adds the ``stress_only`` differences (longer datasets), ``profile="edge"``
        adds the ``edge`` ones."""
        scopes = ["all"] + (["stress_only"] if stress else []) + (["edge"] if profile == "edge" else [])
        return cls(known=known_differences(*scopes), **overrides)


@dataclass
class Verdict:
    compared: int
    twins: int
    matched: int
    known_divergent: int
    unexpected_rules: list[str]
    diverged: list[str]
    now_matching_but_listed: list[str]
    no_twin: list[str]
    per_rule: dict
    ok: bool

    @property
    def unexpected(self) -> int:
        return len(self.unexpected_rules)

    def summary(self, ok: bool | None = None) -> str:
        """``parity: compared=71 matched=47 known-divergent=24 unexpected=0 -> OK`` (pass ``ok`` to fold in other checks)."""
        flag = self.ok if ok is None else ok
        return (f"parity: compared={self.compared} matched={self.matched} known-divergent={self.known_divergent} "
                f"unexpected={self.unexpected} -> {'OK' if flag else 'FAIL'}")

    def to_dict(self) -> dict:
        return {"compared": self.compared, "matched": self.matched, "known_divergent": self.known_divergent,
                "unexpected": self.unexpected, "unexpected_rules": list(self.unexpected_rules), "ok": self.ok}


def verdict_from_counts(compared: int, twins: int, diverged: Iterable[str], known: Iterable[str]) -> dict:
    """Acceptance verdict for pandas-vs-SQL: fails on any unlisted divergence, a short comparison or zero compared."""
    diverged, known = set(diverged), set(known)
    unexpected = sorted(diverged - known)
    return {"compared": compared, "matched": compared - len(diverged), "known_divergent": len(diverged & known),
            "unexpected": len(unexpected), "unexpected_rules": unexpected,
            "ok": not unexpected and compared >= twins and compared > 0}


def sql_result_key(row: dict) -> tuple[str, str, str]:
    """Stable SQL row identity, including the physical series for per-sensor sweeps."""
    return (row.get("equipment_id", ""), row.get("series_id", ""), row.get("sensor_role", ""))


def sql_rows_by_equipment(rows: list[dict] | None) -> dict[str, dict]:
    """Rows by equipment; per-sensor rows (``sensor_role``) are aggregated by role, equipment total = worst role."""
    rows = rows or []
    if not any("sensor_role" in row for row in rows):
        return {r["equipment_id"]: r for r in rows}
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["equipment_id"], []).append(row)
    out = {}
    for equip, group in grouped.items():
        by_role: dict[str, float] = {}
        for row in group:
            role = row.get("sensor_role")
            hours, covered = row.get("fault_hours"), row.get("covered_hours")
            if role is not None and hours is not None and covered is not None and float(covered) > 0:
                by_role[role] = max(float(hours), by_role.get(role, float("-inf")))
        out[equip] = {"equipment_id": equip, "fault_hours": max(by_role.values(), default=None),
                      "sensor_fault_hours": by_role, "sensor_series_rows": group}
    return out


def rule_matches(per: dict, policy: Policy | None = None) -> bool:
    """True when every equipment of one compared rule agrees within the policy tolerance."""
    policy = policy or Policy()
    for v in per.values():
        sql_roles = v.get("sql_sensor_fault_hours")
        pandas_roles = v.get("pandas_sensor_fault_hours")
        if sql_roles is not None or pandas_roles is not None:
            if sql_roles is None or pandas_roles is None or set(sql_roles) != set(pandas_roles):
                return False
            if any(abs(float(sql_roles[r]) - float(pandas_roles[r])) >
                   policy.sensor_abs_tol_h + policy.sensor_rel_tol * abs(float(sql_roles[r])) for r in sql_roles):
                return False
        p = v["pandas"]
        if p is None:
            if v["sql"] > policy.abs_tol_h:
                return False
            continue
        tol = (policy.sensor_abs_tol_h + policy.sensor_rel_tol * abs(float(v["sql"]))
               if "sql_sensor_fault_hours" in v else policy.abs_tol_h)
        if abs(p - v["sql"]) > tol:
            return False
    return True


def compare(sql_rows: Mapping[str, list[dict]], ref_rows: Mapping[str, Mapping[str, dict]],
            policy: Policy | None = None) -> Verdict:
    """Compare engine rows with the pandas reference under ``policy`` (default: ``Policy.default()``)."""
    policy = policy or Policy.default()
    per_rule: dict[str, dict] = {}
    for rule, ref_by_equip in ref_rows.items():
        sql = sql_rows_by_equipment(sql_rows.get(rule))
        per: dict[str, dict] = {}
        for equip, ref in ref_by_equip.items():
            row = sql.get(equip)
            if row is None or row.get("fault_hours") is None:
                continue
            item = {"sql": float(row["fault_hours"]), "pandas": ref.get("pandas"), "status": ref.get("status")}
            if "sensor_fault_hours" in row:
                item["sql_sensor_fault_hours"] = row["sensor_fault_hours"]
                item["pandas_sensor_fault_hours"] = ref.get("pandas_sensor_fault_hours") or {}
                item["pandas_sensor_silence_hours"] = ref.get("pandas_sensor_silence_hours") or {}
            per[equip] = item
        if per:
            per_rule[rule] = per
    diverged = sorted(r for r, per in per_rule.items() if not rule_matches(per, policy))
    v = verdict_from_counts(len(per_rule), len(ref_rows) if policy.require_all_twins else 0, diverged, policy.known)
    return Verdict(
        compared=v["compared"], twins=len(ref_rows), matched=v["matched"], known_divergent=v["known_divergent"],
        unexpected_rules=v["unexpected_rules"], diverged=diverged,
        now_matching_but_listed=sorted(r for r in policy.known if r in per_rule and r not in diverged),
        no_twin=sorted(r for r in sql_rows if r not in ref_rows), per_rule=per_rule, ok=v["ok"])
