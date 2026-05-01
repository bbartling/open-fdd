"""
Join FDD rule YAML inputs, BRICK/TTL column mapping, and model points (Feather refs) for debugging.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from open_fdd.desktop.services.brick_service import BrickService
from open_fdd.engine.runner import col_map_for_rule, load_rule


def _summarize_point(pt: dict[str, Any]) -> dict[str, Any]:
    meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
    ref = str(meta.get("external_ref") or "")
    if len(ref) > 160:
        ref = ref[:157] + "..."
    return {
        "point_id": str(pt.get("id", "")),
        "site_id": str(pt.get("site_id", "")),
        "external_id": str(pt.get("external_id", "")),
        "brick_type": str(pt.get("brick_type", "")),
        "fdd_input": str(pt.get("fdd_input") or ""),
        "feather_or_ref": ref,
    }


def _index_points(points: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    by_external: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_fdd: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pt in points:
        if not isinstance(pt, dict):
            continue
        summary = _summarize_point(pt)
        ext = str(pt.get("external_id") or "").strip()
        if ext:
            by_external[ext].append(summary)
        fi = str(pt.get("fdd_input") or "").strip()
        if fi:
            by_fdd[fi].append(summary)
    return by_external, by_fdd


def _merge_matches(
    *,
    by_external: dict[str, list[dict[str, Any]]],
    by_fdd: dict[str, list[dict[str, Any]]],
    resolved_column: str,
    input_key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    def _dedupe_key(row: dict[str, Any]) -> str:
        pid = str(row.get("point_id") or "").strip()
        if pid:
            return pid
        ext = str(row.get("external_id") or "").strip()
        fi = str(row.get("fdd_input") or "").strip()
        return f"__missing_id__:{ext or fi or id(row)}"

    for row in by_external.get(resolved_column, []):
        merged[_dedupe_key(row)] = row
    for row in by_fdd.get(input_key, []):
        merged[_dedupe_key(row)] = row
    return list(merged.values())


def _iter_rule_yaml_files(rules_dir: Path) -> list[Path]:
    by_name: dict[str, Path] = {}
    for pattern in ("*.yaml", "*.yml"):
        for f in rules_dir.glob(pattern):
            by_name.setdefault(f.name, f)
    return [by_name[k] for k in sorted(by_name.keys())]


def build_fdd_rule_data_lineage(
    *,
    model: dict[str, Any],
    ttl_path: Path,
    rules_dir: Path,
    site_id: str | None = None,
) -> dict[str, Any]:
    """
    For each rule YAML: resolved dataframe columns (via TTL ``mapsToRuleInput`` / BRICK map),
    and model points whose ``external_id`` or ``fdd_input`` aligns.
    """
    column_map = BrickService(ttl_path=ttl_path).resolve_column_map()
    raw_points = model.get("points", []) if isinstance(model.get("points"), list) else []
    points: list[dict[str, Any]] = [p for p in raw_points if isinstance(p, dict)]
    if site_id and str(site_id).strip():
        sid = str(site_id).strip()
        points = [p for p in points if str(p.get("site_id", "")) == sid]
    by_external, by_fdd = _index_points(points)

    rules_out: list[dict[str, Any]] = []
    if not rules_dir.is_dir():
        return {
            "rules_dir": str(rules_dir),
            "ttl_path": str(ttl_path),
            "column_map_size": len(column_map),
            "site_filter": site_id or None,
            "rules": [],
            "note": "Rules directory is missing or not a directory.",
        }

    for path in _iter_rule_yaml_files(rules_dir):
        try:
            rule = load_rule(path)
        except Exception as exc:  # noqa: BLE001
            rules_out.append({"yaml": path.name, "error": str(exc)})
            continue
        cmap = col_map_for_rule(rule, column_map)
        inputs_block = rule.get("inputs", {})
        input_rows: list[dict[str, Any]] = []
        for input_key, resolved_col in cmap.items():
            inp = inputs_block.get(input_key)
            brick_tag = None
            if isinstance(inp, dict):
                brick_tag = inp.get("brick")
            elif isinstance(inp, str):
                brick_tag = None
            matches = _merge_matches(
                by_external=by_external,
                by_fdd=by_fdd,
                resolved_column=str(resolved_col),
                input_key=str(input_key),
            )
            input_rows.append(
                {
                    "input_key": str(input_key),
                    "brick_tag": brick_tag,
                    "resolved_engine_column": str(resolved_col),
                    "model_points": matches,
                    "match_count": len(matches),
                }
            )
        rules_out.append(
            {
                "yaml": path.name,
                "name": rule.get("name"),
                "type": rule.get("type"),
                "flag": rule.get("flag"),
                "inputs": input_rows,
            }
        )

    return {
        "rules_dir": str(rules_dir.resolve()),
        "ttl_path": str(ttl_path),
        "column_map_size": len(column_map),
        "site_filter": site_id or None,
        "rules": rules_out,
        "note": (
            "resolved_engine_column is what the rule runner expects on the dataframe; "
            "model_points lists points where external_id equals that column and/or fdd_input equals the rule input key. "
            "feather_or_ref is metadata.external_ref from the JSON model (same as ofdd:externalReference in TTL)."
        ),
    }
