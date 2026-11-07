"""Read-only agent analytics tools, run on the NF box (standard library only).

The six tools live in ONE place, the NF app's ``analytics`` on-request hook (``nf-app/hooks/analytics.js``),
which reuses the dashboard math (weekly runtime, cooling bins, economizer, fault timeline, role binding).
This module only transports: it starts the hook with ``args`` (NF StartHook), waits for the run and returns
the answer. No math here, and the hook cannot write points, schedules or BACnet values.

    from open_fdd.nf import NFClient
    from open_fdd.nf.analytics import analyze
    client = NFClient.from_env()
    out = analyze(client, "analyze_ahu_weekly_runtime", site="site-a", days=28)
    for row in out["rows"]:                       # keyed by equipUuid (+ siteRef, equipRef)
        print(row["equipUuid"], row["week"], row["run_hours"], row["after_hours"])

Tools (args -> result keys):
    analyze_ahu_weekly_runtime  site? equip? days=28   rows: run_hours schedule_hours in_schedule_hours after_hours
                                                        partial_week mean_oat_on_c schedule_source schedule_label
    analyze_mechanical_cooling  site? equip? days=28   rows: bins[6] (hours per SI OAT bin) total_hours
    analyze_economizer          site? equip? days=7    rows: n n_identifiable median_residual_k mae_k
    get_fdd_fault_timeline      site? equip rule days=1 dense?   timeline [{ts, state: confirmed|ok|unknown}] summary
    resolve_equipment_roles     equip (uuid, or id with site)    roles {role: [points]} runnable_rules
    explain_missing_rcx_view    view site? equip?                available missing_roles reasons equips[]
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from open_fdd.nf.client import NFClient, NFError

APP_ID = "open-fdd"
HOOK_ID = "analytics"
TOOLS = (
    "analyze_ahu_weekly_runtime",
    "analyze_mechanical_cooling",
    "analyze_economizer",
    "get_fdd_fault_timeline",
    "resolve_equipment_roles",
    "explain_missing_rcx_view",
)
SHORT = {  # CLI names: `open-fdd-nf analyze weekly-runtime`
    "weekly-runtime": "analyze_ahu_weekly_runtime",
    "cooling": "analyze_mechanical_cooling",
    "economizer": "analyze_economizer",
    "fault-timeline": "get_fdd_fault_timeline",
    "roles": "resolve_equipment_roles",
    "explain-view": "explain_missing_rcx_view",
}


def tool_args(tool: str, *, site: str | None = None, equip: str | None = None, rule: str | None = None,
              days: float | None = None, view: str | None = None, dense: bool = False) -> dict[str, Any]:
    """The hook's ``args`` for a tool: only what was given (the hook has the per-tool defaults)."""
    tool = SHORT.get(tool, tool)
    if tool not in TOOLS:
        raise NFError(f"unknown tool {tool!r}; one of {', '.join(TOOLS)}")
    args: dict[str, Any] = {"tool": tool}
    for key, val in (("site", site), ("equip", equip), ("rule", rule), ("viewId", view)):
        if val:
            args[key] = val
    if days is not None:
        args["days"] = float(days)
    if dense:
        args["dense"] = True
    return args


def run_result(run: Mapping[str, Any]) -> dict:
    """The hook's answer from a finished run: the last JSON event the hook logged (the same object it returned)."""
    if run.get("state") != "STATE_SUCCESS":
        raise NFError(f"analytics run ended {run.get('state')}: {str(run.get('error') or run.get('message') or '')[:200]}".rstrip(": "))
    events = [e for g in (run.get("results") or {}).values() if isinstance(g, Mapping) for e in (g.get("events") or [])]
    for ev in reversed(events):
        try:
            out = json.loads(ev.get("message", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(out, dict) and "ok" in out:
            return out
    raise NFError("analytics run finished without a result event (see the run's logs)")


def analyze(client: NFClient, tool: str, *, timeout: float = 120.0, **kw: Any) -> dict:
    """Run one analytics tool on the box and return its result dict. Raises NFError when the hook reports ``ok: false``.

    ``kw`` = site, equip, rule, days, view, dense (see ``tool_args``). The error carries the hook's message, and for an
    ambiguous equip the candidate equipUuids.
    """
    run = client.run_hook(APP_ID, HOOK_ID, tool_args(tool, **kw), timeout=timeout)
    out = run_result(run)
    if not out.get("ok"):
        msg = str(out.get("error") or "analytics tool failed")
        cands = out.get("candidates")
        if cands:
            msg += "; candidates: " + ", ".join(f"{c.get('siteRef')}/{c.get('equipRef')}={c.get('equipUuid')}" for c in cands)
        raise NFError(msg)
    return out
