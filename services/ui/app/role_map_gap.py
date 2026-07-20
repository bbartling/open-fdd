"""Role-map gap report — per-equipment missing roles vs applicable cookbook rules."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.role_map import apply_role_map
from app.rules import cookbook_catalog as cb
from app.rules.runner import infer_equipment_kind, merge_weather
from app.site_model import resolve_equipment_type
from app.weather_resolver import has_bas_oat, has_web_oat


def _candidate_columns(raw: pd.DataFrame, role: str, *, limit: int = 8) -> list[str]:
    """Heuristic column suggestions for an unmapped role."""
    cols = [str(c) for c in raw.columns]
    role_l = role.lower().replace("_pct", "").replace("_", "")
    tokens = [t for t in role.lower().replace("_pct", "").split("_") if t]
    scored: list[tuple[int, str]] = []
    for c in cols:
        cl = c.lower().replace("-", "").replace("_", "")
        score = 0
        if role_l and role_l in cl:
            score += 5
        for t in tokens:
            if t and t in cl:
                score += 1
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, c in scored[:limit]]


def build_role_map_gap_report(
    frames: dict[str, pd.DataFrame],
    role_map: dict[str, dict[str, str]],
    *,
    weather: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per equipment with mapped/missing roles and skip impact."""
    rows: list[dict[str, Any]] = []
    for eq_id, raw in sorted(frames.items()):
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        kind = infer_equipment_kind(eq_id, equipment_type=et, df=raw, role_map=role_map)
        mapped = apply_role_map(raw, eq_id, role_map)
        mapped.attrs.update(raw.attrs)
        enriched = merge_weather(mapped, weather)
        mapped_roles = sorted(
            r
            for r in set(role_map.get(eq_id, {})).union(
                c for c in enriched.columns if isinstance(c, str) and not str(c).startswith("wx_")
            )
            if r in enriched.columns and enriched[r].notna().any()
        )
        # Prefer explicit role_map keys that landed
        explicit = sorted(
            r for r, col in (role_map.get(eq_id) or {}).items() if col and r in enriched.columns
        )
        if explicit:
            mapped_roles = sorted(set(explicit) | {r for r in mapped_roles if r in explicit or r in enriched.columns})

        applicable = [r for r in cb.RULES if kind == "unknown" or kind in r.equipment_kinds]
        applicable_ids = [r.id for r in applicable]
        missing_by_rule: dict[str, list[str]] = {}
        skipped_rules: list[str] = []
        all_missing: set[str] = set()
        for rule in applicable:
            miss: list[str] = []
            if rule.sensor_sweep or rule.control_output_sweep:
                continue
            for role in rule.required_roles:
                if role == "outside-air-temp":
                    if (
                        ("outside-air-temp" in enriched.columns and enriched["outside-air-temp"].notna().any())
                        or ("oa_t_effective" in enriched.columns and enriched["oa_t_effective"].notna().any())
                    ):
                        continue
                    miss.append(role)
                    continue
                if role == "web-outside-air-temp":
                    if not has_web_oat(enriched):
                        miss.append(role)
                    continue
                if role not in enriched.columns or enriched[role].notna().sum() == 0:
                    miss.append(role)
            if rule.id == "OAT-METEO":
                miss = []
                if not has_bas_oat(enriched):
                    miss.append("bas oa_t")
                if not has_web_oat(enriched):
                    miss.append("web-outside-air-temp")
            if miss:
                missing_by_rule[rule.id] = miss
                skipped_rules.append(rule.id)
                all_missing.update(miss)

        candidates: dict[str, list[str]] = {}
        for role in sorted(all_missing):
            if role.startswith("bas "):
                continue
            candidates[role] = _candidate_columns(raw, role)

        rows.append(
            {
                "equipment_id": eq_id,
                "equipment_type": et,
                "mapped_roles": ",".join(explicit or mapped_roles),
                "mapped_role_count": len(explicit or mapped_roles),
                "applicable_rules": ",".join(applicable_ids),
                "applicable_rule_count": len(applicable_ids),
                "missing_roles": ",".join(sorted(all_missing)),
                "missing_role_count": len(all_missing),
                "skipped_rules_missing_roles": ",".join(skipped_rules),
                "skipped_rule_count": len(skipped_rules),
                "candidate_columns": "; ".join(
                    f"{role}=[{'|'.join(cols)}]" for role, cols in sorted(candidates.items()) if cols
                ),
                "has_web_weather_fallback": has_web_oat(enriched) or has_web_oat(weather),
                "has_bas_oat": has_bas_oat(enriched),
                "oa_t_effective_source": enriched.attrs.get("oa_t_effective_source"),
            }
        )
    return pd.DataFrame(rows)
