"""Stage-1 agent CLI stubs: evidence import + dual-rail Inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .contracts import (
    EngineeringInput,
    InputRail,
    SourceType,
    AssumptionMethod,
    list_missing_inputs,
    validate_engineering_inputs,
    validate_simulation_evidence,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _input_from_dict(d: dict[str, Any]) -> EngineeringInput:
    return EngineeringInput(
        input_id=str(d["input_id"]),
        display_name=str(d.get("display_name") or d["input_id"]),
        value=d.get("value"),
        unit=str(d.get("unit") or ""),
        rail=InputRail(d.get("rail") or "shared"),
        source_type=SourceType(d.get("source_type") or "human_entered"),
        confidence=str(d.get("confidence") or "unknown"),
        editable=bool(d.get("editable", True)),
        validation_status=str(d.get("validation_status") or "ok"),
        validation_message=str(d.get("validation_message") or ""),
        assumption_note=str(d.get("assumption_note") or ""),
        assumption_method=AssumptionMethod(d.get("assumption_method") or "unknown"),
        linked_measure_ids=list(d.get("linked_measure_ids") or []),
        source_reference=str(d.get("source_reference") or ""),
        notes=str(d.get("notes") or ""),
    )


def cmd_import_energyplus_evidence(path: Path, *, strict: bool = True) -> dict[str, Any]:
    doc = _load_json(path)
    issues = validate_simulation_evidence(doc, strict=strict)
    return {
        "ok": not issues,
        "path": str(path),
        "schema_version": doc.get("schema_version") if isinstance(doc, dict) else None,
        "issues": issues,
        "measure_count": len((doc or {}).get("individual_measures") or [])
        if isinstance(doc, dict)
        else 0,
    }


def cmd_list_workbook_inputs(path: Path) -> dict[str, Any]:
    doc = _load_json(path)
    raw = doc.get("inputs") if isinstance(doc, dict) else None
    if raw is None and isinstance(doc, list):
        raw = doc
    if not isinstance(raw, list):
        return {"ok": False, "issues": ["expected {inputs:[...]} or a list"], "inputs": []}
    inputs = [_input_from_dict(x) for x in raw if isinstance(x, dict)]
    issues = validate_engineering_inputs(inputs)
    return {
        "ok": not issues,
        "count": len(inputs),
        "inputs": [i.as_dict() for i in inputs],
        "issues": issues,
        "missing": list_missing_inputs(inputs),
    }


def cmd_list_missing_inputs(path: Path) -> dict[str, Any]:
    listed = cmd_list_workbook_inputs(path)
    return {
        "ok": listed.get("ok", False),
        "missing": listed.get("missing") or [],
        "issues": listed.get("issues") or [],
    }


def cmd_propose_input_update(
    path: Path,
    *,
    input_id: str,
    value: Any,
    reason: str,
    assumption_note: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Propose an Inputs update; Stage 1 always dry_run (no workbook write)."""
    listed = cmd_list_workbook_inputs(path)
    if not listed.get("ok") and listed.get("issues"):
        # Still allow propose against partial manifests
        pass
    match = next((i for i in listed.get("inputs") or [] if i.get("input_id") == input_id), None)
    action = {
        "action": "propose_input",
        "input_id": input_id,
        "old_value": None if match is None else match.get("value"),
        "new_value": value,
        "reason": reason,
        "assumption_note": assumption_note,
        "dry_run": dry_run,
        "persisted": False,
    }
    if not dry_run:
        action["warning"] = "Stage 1 CLI does not persist workbook edits yet (use dry_run)"
    return {"ok": True, "action": action, "manifest_issues": listed.get("issues") or []}


def agent_cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="open-fdd-ecm-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import_energyplus_evidence")
    imp.add_argument("path", type=Path)
    imp.add_argument("--lenient", action="store_true")

    li = sub.add_parser("list_workbook_inputs")
    li.add_argument("path", type=Path)

    lm = sub.add_parser("list_missing_inputs")
    lm.add_argument("path", type=Path)

    prop = sub.add_parser("propose_input_update")
    prop.add_argument("path", type=Path)
    prop.add_argument("--input-id", required=True)
    prop.add_argument("--value", required=True)
    prop.add_argument("--reason", required=True)
    prop.add_argument("--assumption-note", default="")
    prop.add_argument("--apply", action="store_true", help="ignored in Stage 1 (dry_run only)")

    args = parser.parse_args(argv)
    if args.command == "import_energyplus_evidence":
        out = cmd_import_energyplus_evidence(args.path, strict=not args.lenient)
    elif args.command == "list_workbook_inputs":
        out = cmd_list_workbook_inputs(args.path)
    elif args.command == "list_missing_inputs":
        out = cmd_list_missing_inputs(args.path)
    elif args.command == "propose_input_update":
        raw_val: Any = args.value
        try:
            raw_val = json.loads(args.value)
        except json.JSONDecodeError:
            pass
        out = cmd_propose_input_update(
            args.path,
            input_id=args.input_id,
            value=raw_val,
            reason=args.reason,
            assumption_note=args.assumption_note,
            dry_run=not args.apply,
        )
    else:
        parser.error(f"unknown command {args.command}")
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok", False) else 1


__all__ = [
    "cmd_import_energyplus_evidence",
    "cmd_list_workbook_inputs",
    "cmd_list_missing_inputs",
    "cmd_propose_input_update",
    "agent_cli_main",
]
