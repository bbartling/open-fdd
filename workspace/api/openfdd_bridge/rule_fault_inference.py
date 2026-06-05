"""Infer check-engine fault codes for Rule Lab rules via local Ollama + catalog context."""

from __future__ import annotations

import json
import re
from typing import Any

from .fault_catalog import COOKBOOK_PATTERNS, entry_for_code, is_valid_code
from .fault_catalog_scope import build_applicable_payload

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _applicable_code_summaries(site_id: str | None, *, limit: int = 48) -> list[dict[str, str]]:
    payload = build_applicable_payload(site_id)
    applicable = {str(f).strip().upper() for f in (payload.get("applicable_families") or []) if str(f).strip()}
    families = payload.get("families") if isinstance(payload.get("families"), list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for fam_block in families:
        fam = str(fam_block.get("family") or "").strip().upper()
        if applicable and fam and fam not in applicable:
            continue
        for cat in fam_block.get("categories") or []:
            if not isinstance(cat, dict):
                continue
            for entry in cat.get("codes") or []:
                if not isinstance(entry, dict):
                    continue
                code = str(entry.get("code") or "").strip().upper()
                if not code or code in seen or not is_valid_code(code):
                    continue
                seen.add(code)
                patterns = entry.get("cookbook_patterns") or []
                out.append(
                    {
                        "code": code,
                        "family": fam,
                        "title": str(entry.get("title") or ""),
                        "category": str(cat.get("label") or entry.get("category") or ""),
                        "severity": str(entry.get("severity") or ""),
                        "cookbook_patterns": ",".join(str(p) for p in patterns[:3]),
                    }
                )
                if len(out) >= limit:
                    return out
    return out


def _deterministic_guess(name: str, code: str, config: dict[str, Any]) -> list[str]:
    """Keyword/cookbook fallback when Ollama is offline."""
    blob = f"{name}\n{code}\n{json.dumps(config, sort_keys=True)}".lower()
    guesses: list[str] = []
    if any(k in blob for k in ("flatline", "spread", "stuck", "stale", "nan")):
        guesses.extend(["VAV-C", "AHU-A", "BLD-D"])
    if any(k in blob for k in ("high", "low", "oob", "band", "threshold", "cfg")):
        guesses.extend(["VAV-B", "AHU-B", "CH-B"])
    if "priority" in blob or "command" in blob:
        guesses.append("AHU-F")
    out: list[str] = []
    for g in guesses:
        c = g.upper()
        if is_valid_code(c) and c not in out:
            out.append(c)
    return out[:3]


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(raw)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def infer_fault_codes_for_rule(
    *,
    name: str,
    code: str,
    mode: str = "rule",
    config: dict[str, Any] | None = None,
    severity: str = "warning",
    site_id: str | None = None,
) -> dict[str, Any]:
    """Map rule Python to fixed catalog codes; narrative explains HVAC / check-engine fit."""
    from . import ollama_client

    cfg = config if isinstance(config, dict) else {}
    catalog = _applicable_code_summaries(site_id)
    scope = build_applicable_payload(site_id)
    code_snip = (code or "").strip()
    if len(code_snip) > 4000:
        code_snip = code_snip[:4000] + "\n# … truncated …"

    system = (
        "You are an Open-FDD HVAC fault-detection engineer on an OT edge host. "
        "Map a Rule Lab Python rule to the fixed check-engine fault catalog (letter suffix only, e.g. VAV-C, AHU-B). "
        "Rules detect sensor flatlines, performance drift, simultaneous heat/cool, I/O mismatch, stale polls, etc. "
        f"Cookbook patterns: {json.dumps(COOKBOOK_PATTERNS, separators=(',', ':'))}. "
        "Reply with ONLY one JSON object (no markdown): "
        '{"fault_codes":["VAV-C"],"narrative":"2-4 sentences on HVAC health + why these codes fit",'
        '"similar":[{"code":"VAV-C","title":"short","relation":"why similar"}]}. '
        "Pick 1–3 codes from applicable_catalog only. Do not invent codes. "
        "If the rule is generic or unclear, pick the closest sensor/performance codes and say so."
    )
    user_payload = {
        "site_id": scope.get("site_id"),
        "equipment_sample": scope.get("equipment_sample") or [],
        "applicable_families": scope.get("applicable_families") or [],
        "rule": {
            "name": name,
            "mode": mode,
            "severity": severity,
            "config": cfg,
            "code": code_snip,
        },
        "applicable_catalog": catalog,
    }
    user = f"Rule + site context:\n{json.dumps(user_payload, separators=(',', ':'))}\n\nJSON:"

    if not ollama_client.gpu_available():
        result = {"ok": False, "error": "no GPU — skipped Ollama inference"}
    else:
        result = ollama_client.chat(user, system=system, history=[], timeout=90.0)
    parsed = _parse_llm_json(str(result.get("reply") or "")) if result.get("ok") else None

    fault_codes: list[str] = []
    similar: list[dict[str, str]] = []
    narrative = ""

    if parsed:
        narrative = str(parsed.get("narrative") or "").strip()
        raw_codes = parsed.get("fault_codes")
        if isinstance(raw_codes, list):
            for raw in raw_codes:
                c = str(raw or "").strip().upper()
                if is_valid_code(c) and c not in fault_codes:
                    fault_codes.append(c)
        raw_similar = parsed.get("similar")
        if isinstance(raw_similar, list):
            for item in raw_similar[:6]:
                if not isinstance(item, dict):
                    continue
                c = str(item.get("code") or "").strip().upper()
                if not is_valid_code(c):
                    continue
                similar.append(
                    {
                        "code": c,
                        "title": str(item.get("title") or (entry_for_code(c) or {}).get("title") or ""),
                        "relation": str(item.get("relation") or ""),
                    }
                )

    source = "ollama" if fault_codes and result.get("ok") else "deterministic"
    ollama_error = str(result.get("error") or "")

    if not fault_codes:
        fault_codes = _deterministic_guess(name, code, cfg)
        if fault_codes and not narrative:
            titles = [entry_for_code(c).get("title", c) if entry_for_code(c) else c for c in fault_codes]
            narrative = (
                f"Ollama unavailable ({ollama_error or 'offline'}). "
                f"Keyword match suggests: {', '.join(f'{c} ({t})' for c, t in zip(fault_codes, titles))}."
            )
            source = "deterministic"

    if fault_codes and not similar:
        for c in fault_codes[:3]:
            ent = entry_for_code(c) or {}
            similar.append(
                {
                    "code": c,
                    "title": str(ent.get("title") or ""),
                    "relation": str(ent.get("description") or "")[:160],
                }
            )

    assigned = scope.get("assigned_rules") if isinstance(scope.get("assigned_rules"), list) else []
    related_rules = [
        r
        for r in assigned
        if isinstance(r, dict)
        and any(fc in fault_codes for fc in (r.get("fault_codes") or [r.get("fault_code")]))
    ][:5]

    return {
        "ok": bool(fault_codes),
        "fault_codes": fault_codes,
        "fault_code": fault_codes[0] if fault_codes else "",
        "narrative": narrative,
        "similar": similar,
        "related_assigned_rules": related_rules,
        "source": source,
        "ollama_ok": bool(result.get("ok")),
        "ollama_error": ollama_error,
        "applicable_catalog_count": len(catalog),
    }
