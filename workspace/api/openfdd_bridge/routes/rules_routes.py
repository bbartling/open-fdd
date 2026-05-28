from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from open_fdd.engine import RuleRunner

from ..data_loader import load_demo_dataframe
from ..deps import require_user
from ..paths import data_dir

router = APIRouter(prefix="/api/rules", tags=["rules"], dependencies=[Depends(require_user)])


class RunRulesBody(BaseModel):
    site_id: str | None = None
    column_map: dict[str, str] = Field(default_factory=dict)
    skip_missing_columns: bool = False
    rules_path: str | None = None


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
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"rules path not found: {path}")
        runner = RuleRunner(rules_path=str(path.parent if path.suffix else path))
    elif rules_dir.is_dir() and any(rules_dir.glob("*.yaml")):
        runner = RuleRunner(rules_path=str(rules_dir))
    else:
        raise HTTPException(
            status_code=400,
            detail="no rules in workspace/data/rules — add YAML or pass rules_path",
        )
    df = load_demo_dataframe(body.site_id)
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
        "flag_columns": flag_cols,
        "flag_totals": {c: int(out[c].sum()) for c in flag_cols},
        "preview": preview.to_dict(orient="records"),
    }


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
