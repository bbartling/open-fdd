"""Cross-sensor rule evaluation and DynamoDB summary helpers (AWS ``fdd_lambda`` parity)."""

from __future__ import annotations

from typing import Any

from open_fdd.playground.cookbook import DEFAULT_ROLLING_AVG_MINUTES, attach_rolling_avg, normalize_rolling_avg_minutes
from open_fdd.playground.sandbox import sweep_rule


def readings_to_rows(readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build row dicts for ``evaluate()`` from historian samples (degF + ts_ms)."""
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(readings):
        ts_iso = r.get("ts_iso") or r.get("ts") or ""
        rows.append(
            {
                "row": i,
                "ts_ms": int(r["ts_ms"]),
                "ts": str(ts_iso).replace("T", " ")[:19],
                "degF": float(r["degF"]),
                "degC": float(r.get("degC", 0)),
                "temp": float(r["degF"]),
                "seq": r.get("seq"),
                "source": r.get("source"),
            }
        )
    return rows


def slim_fdd_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky chart payloads before writing FDD status to DynamoDB (~400 KB item limit)."""
    return {k: v for k, v in summary.items() if k not in ("ts_ms", "flag_series", "aux_series")}


def build_series_context(
    series_map: dict[str, list[dict[str, Any]]],
    row_index: int,
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Per-row ``series`` dict for cross-sensor rules.
    ``aliases`` maps rule keys (e.g. SAT) → ``series_id``.
    Each entry: ``{"values": [...], "current": float|None, "series_id": str}``.
    """
    ctx: dict[str, Any] = {}
    alias_to_sid = aliases or {}
    sid_to_alias = {v: k for k, v in alias_to_sid.items()}

    for sid, samples in series_map.items():
        values = [s.get("value") for s in samples]
        cur = values[row_index] if 0 <= row_index < len(values) else None
        entry = {"values": values, "current": cur, "series_id": sid}
        ctx[sid] = entry
        alias = sid_to_alias.get(sid)
        if alias:
            ctx[alias] = entry
    return ctx


def evaluate_rules_on_series(
    rules: list[dict[str, Any]],
    primary_rows: list[dict[str, Any]],
    series_map: dict[str, list[dict[str, Any]]],
    *,
    default_rolling_avg_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
) -> dict[str, list[int]]:
    """Evaluate rules with cross-sensor ``series`` context aligned to ``primary_rows`` length."""
    n = len(primary_rows)
    if n == 0:
        return {}
    out: dict[str, list[int]] = {}
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        code = rule.get("code") or ""
        cfg = rule.get("config") or {}
        aliases = cfg.get("series_aliases") or {}
        minutes = normalize_rolling_avg_minutes(
            cfg.get("rolling_avg_minutes", default_rolling_avg_minutes)
        )
        flags = [0] * n
        for i in range(n):
            series_ctx = build_series_context(series_map, i, aliases=aliases)
            row = primary_rows[i]
            chunk_flags, _events = sweep_rule(
                code,
                cfg,
                [row],
                capture_print=False,
                rolling_avg_minutes=minutes,
                series_ctx=series_ctx,
            )
            if chunk_flags and chunk_flags[0]:
                flags[i] = 1
        out[rule["id"]] = flags
    return out
