from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from open_fdd.engine import RuleRunner, load_rule

from ..data_loader import load_frame_for_run
from ..deps import require_roles, require_user
from ..fault_catalog import is_valid_code
from ..fdd_runner import run_batch
from ..paths import data_dir
from ..rule_store import RuleStore
from ..rule_source import read_source, write_source

router = APIRouter(prefix="/api/rules", tags=["rules"], dependencies=[Depends(require_user)])


class RunRulesBody(BaseModel):
    site_id: str | None = None
    column_map: dict[str, str] = Field(default_factory=dict)
    skip_missing_columns: bool = False
    rules_path: str | None = None


class AppliesTo(BaseModel):
    equipment_type: str = ""
    brick_type: str = ""
    site_ids: list[str] = Field(default_factory=list)


class SaveRuleBody(BaseModel):
    id: str | None = None
    name: str = "Untitled rule"
    description: str = ""
    mode: str = "rule"
    code: str
    fault_code: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    column_map: dict[str, str] = Field(default_factory=dict)
    applies_to: AppliesTo = Field(default_factory=AppliesTo)
    bindings: dict[str, list[str]] = Field(default_factory=dict)
    severity: str = "warning"
    enabled: bool = True


class RuleSourceBody(BaseModel):
    code: str


class RuleBindingsBody(BaseModel):
    rule_id: str
    point_ids: list[str] = Field(default_factory=list)
    equipment_ids: list[str] = Field(default_factory=list)
    brick_types: list[str] = Field(default_factory=list)


class BatchBody(BaseModel):
    limit: int = Field(default=1000, ge=1, le=5000)


@router.get("/list")
def list_rules() -> dict:
    rules_dir = data_dir() / "rules"
    if not rules_dir.is_dir():
        return {"rules": []}
    files = sorted(rules_dir.glob("*.yaml")) + sorted(rules_dir.glob("*.yml"))
    return {"rules": [p.name for p in files]}


@router.post("/run")
def run_rules(body: RunRulesBody) -> dict:
    rules_dir = data_dir() / "rules"
    if body.rules_path:
        path = Path(body.rules_path)
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"rules path not found: {path}")
        if path.is_dir():
            runner = RuleRunner(rules_path=str(path))
        elif path.is_file() and path.suffix in {".yaml", ".yml"}:
            runner = RuleRunner(rules=[load_rule(path)])
        else:
            raise HTTPException(status_code=400, detail=f"unsupported rules path: {path}")
    elif rules_dir.is_dir() and (
        any(rules_dir.glob("*.yaml")) or any(rules_dir.glob("*.yml"))
    ):
        runner = RuleRunner(rules_path=str(rules_dir))
    else:
        raise HTTPException(
            status_code=400,
            detail="no rules in workspace/data/rules — add YAML or pass rules_path",
        )
    df, source = load_frame_for_run(body.site_id)
    out = runner.run(
        df,
        column_map=body.column_map or None,
        skip_missing_columns=body.skip_missing_columns,
    )
    flag_cols = [c for c in out.columns if str(c).endswith("_flag")]
    preview = out.head(80).copy()
    if "timestamp" in preview.columns:
        preview["timestamp"] = preview["timestamp"].astype(str)
    return {
        "ok": True,
        "rows": len(out),
        "data_source": source,
        "flag_columns": flag_cols,
        "flag_totals": {c: int(out[c].sum()) for c in flag_cols},
        "preview": preview.to_dict(orient="records"),
    }


@router.get("/saved")
def list_saved_rules(_user: dict = Depends(require_user)) -> dict:
    return {"rules": RuleStore().list_rules()}


@router.post("/save")
def save_rule(body: SaveRuleBody, user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    saved_by = str(user.get("sub") or user.get("role") or "operator")
    if body.fault_code and not is_valid_code(body.fault_code):
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown fault code '{body.fault_code}'. Use a fixed code from "
                "/api/faults/catalog — codes must not be invented."
            ),
        )
    try:
        entry = RuleStore().upsert(body.model_dump(), saved_by=saved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": entry}


@router.get("/saved/{rule_id}/source")
def get_rule_source(rule_id: str, _user: dict = Depends(require_user)) -> dict:
    rule = RuleStore().get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"rule not found: {rule_id}")
    path = str(rule.get("source_path") or "")
    code = read_source(path) if path else str(rule.get("code") or "")
    return {"ok": True, "rule_id": rule_id, "path": path, "code": code}


@router.put("/saved/{rule_id}/source")
def put_rule_source(
    rule_id: str,
    body: RuleSourceBody,
    user: dict = Depends(require_roles("integrator", "agent")),
) -> dict:
    store = RuleStore()
    rule = store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"rule not found: {rule_id}")
    if not body.code.strip():
        raise HTTPException(status_code=400, detail="code is required")
    path = write_source(
        rule_id=rule_id,
        name=str(rule.get("name") or rule_id),
        code=body.code,
        existing_path=str(rule.get("source_path") or "") or None,
    )
    entry = store.upsert({**rule, "code": body.code, "source_path": path}, saved_by=str(user.get("sub") or "operator"))
    return {"ok": True, "path": path, "rule": entry}


@router.post("/bindings")
def update_rule_bindings(
    body: RuleBindingsBody,
    user: dict = Depends(require_roles("integrator", "agent", "operator")),
) -> dict:
    store = RuleStore()
    rule = store.get(body.rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"rule not found: {body.rule_id}")
    entry = store.upsert(
        {
            **rule,
            "bindings": {
                "point_ids": body.point_ids,
                "equipment_ids": body.equipment_ids,
                "brick_types": body.brick_types,
            },
        },
        saved_by=str(user.get("sub") or "operator"),
    )
    return {"ok": True, "rule": entry}


@router.delete("/saved/{rule_id}")
def delete_saved_rule(rule_id: str, _user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    removed = RuleStore().delete(rule_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"rule not found: {rule_id}")
    return {"ok": True, "deleted": rule_id}


@router.post("/batch")
def run_saved_batch(body: BatchBody, _user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    return run_batch(limit=body.limit)


@router.get("/drafts")
def load_drafts() -> dict:
    path = data_dir() / "playground" / "draft_rules.json"
    if not path.is_file():
        return {"rules": []}
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/drafts")
def save_drafts(payload: dict[str, Any]) -> dict:
    path = data_dir() / "playground" / "draft_rules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(path)}
