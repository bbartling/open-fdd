from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..deps import require_roles, require_user
from ..fault_catalog import is_valid_code
from ..fdd_runner import run_batch
from ..paths import data_dir
from ..rule_bindings import apply_bind_op, build_assignments_view
from ..rule_store import RuleStore
from ..rule_kit import RuleKitError, build_rule_kit_zip, ingest_uploaded_rule
from ..rule_source import read_source, write_source
from ..model_service import ModelService
from ..site_defaults import ensure_default_site
from ..ttl_service import TtlService

router = APIRouter(prefix="/api/rules", tags=["rules"], dependencies=[Depends(require_user)])


class AppliesTo(BaseModel):
    equipment_type: str = ""
    brick_type: str = ""
    site_ids: list[str] = Field(default_factory=list)


class SaveRuleBody(BaseModel):
    id: str | None = None
    name: str = "Untitled rule"
    description: str = ""
    mode: str = "rule"
    backend: str = ""
    code: str
    fault_code: str = ""
    fault_codes: list[str] = Field(default_factory=list)
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
    direct_point_ids: list[str] | None = None
    equipment_ids: list[str] = Field(default_factory=list)
    brick_types: list[str] = Field(default_factory=list)


class RuleBindOpBody(BaseModel):
    """Merge-style bind/unbind — same semantics as the dashboard ruleBindings helpers."""

    rule_id: str
    op: str = Field(pattern="^(add|remove)$")
    kind: str = Field(pattern="^(point|equipment|brick_type)$")
    target_id: str
    point_ids: list[str] = Field(default_factory=list)


class BatchBody(BaseModel):
    limit: int = Field(default=1000, ge=1, le=50000)
    chunk_hours: float = Field(default=6, ge=0, le=168)
    lookback_hours: float = Field(default=1, ge=0, le=720)
    use_chunks: bool | None = None


class InferFaultCodesBody(BaseModel):
    name: str = "Untitled rule"
    code: str
    mode: str = "rule"
    config: dict[str, Any] = Field(default_factory=dict)
    severity: str = "warning"
    site_id: str | None = None


@router.get("/saved")
def list_saved_rules(_user: dict = Depends(require_user)) -> dict:
    return {"rules": RuleStore().list_rules()}


@router.get("/export-kit")
def export_rule_kit(
    site_id: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    lookback_hours: float = Query(default=24, ge=1, le=720),
    point_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    _user: dict = Depends(require_roles("integrator", "agent", "operator")),
) -> Response:
    """Download zip: rule.py + data.py + sample.feather + column_map.json + README."""
    point_keys = [point_id.strip()] if point_id and point_id.strip() else None
    try:
        payload, filename = build_rule_kit_zip(
            site_id=site_id,
            rule_id=rule_id,
            lookback_hours=lookback_hours,
            limit=limit,
            point_keys=point_keys,
        )
    except RuleKitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload")
async def upload_rule_py(
    file: UploadFile = File(...),
    rule_id: str | None = Form(default=None),
    user: dict = Depends(require_roles("integrator", "agent")),
) -> dict:
    """Upload rule.py — Arrow-only, validated, named from filename when new."""
    raw_name = str(file.filename or "rule.py")
    body = await file.read()
    try:
        code = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="rule.py must be UTF-8 text") from exc
    try:
        entry = ingest_uploaded_rule(
            code=code,
            filename=raw_name,
            rule_id=(rule_id or "").strip() or None,
            saved_by=str(user.get("sub") or user.get("role") or "integrator"),
        )
    except RuleKitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": entry, "filename": raw_name}


def _validate_fault_codes(codes_raw: list[str]) -> list[str]:
    validated: list[str] = []
    for raw in codes_raw:
        code = str(raw).strip().upper()
        if not code:
            continue
        if not is_valid_code(code):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown fault code '{raw}'. Use a letter-suffix code from "
                    "/api/faults/catalog (e.g. VAV-C, AHU-B) — not equipment names like VAV-03."
                ),
            )
        if code not in validated:
            validated.append(code)
    return validated


@router.post("/infer-fault-codes")
def infer_fault_codes_route(
    body: InferFaultCodesBody,
    _user: dict = Depends(require_roles("integrator", "agent")),
) -> dict:
    """Ollama + BRICK-scoped catalog — suggest fault codes and HVAC narrative for a rule."""
    from ..rule_fault_inference import infer_fault_codes_for_rule

    svc = ModelService()
    ttl = TtlService()
    site_id = (body.site_id or "").strip() or ensure_default_site(svc, ttl)
    return {
        "ok": True,
        **infer_fault_codes_for_rule(
            name=body.name,
            code=body.code,
            mode=body.mode,
            config=body.config,
            severity=body.severity,
            site_id=site_id,
        ),
    }


@router.post("/save")
def save_rule(body: SaveRuleBody, user: dict = Depends(require_roles("integrator", "agent"))) -> dict:
    saved_by = str(user.get("sub") or user.get("role") or "operator")
    payload = body.model_dump()
    codes_raw = [str(c).strip() for c in (body.fault_codes or []) if str(c).strip()]
    if not codes_raw and body.fault_code:
        codes_raw = [str(body.fault_code).strip()]
    validated = _validate_fault_codes(codes_raw) if codes_raw else []
    fault_inference: dict[str, Any] | None = None
    if not validated:
        from ..rule_fault_inference import infer_fault_codes_for_rule

        svc = ModelService()
        ttl = TtlService()
        site_id = ensure_default_site(svc, ttl)
        applies = body.applies_to.site_ids if body.applies_to else []
        if applies:
            site_id = str(applies[0]).strip() or site_id
        fault_inference = infer_fault_codes_for_rule(
            name=body.name,
            code=body.code,
            mode=body.mode,
            config=body.config,
            severity=body.severity,
            site_id=site_id,
        )
        validated = _validate_fault_codes(fault_inference.get("fault_codes") or [])
    payload["fault_codes"] = validated
    payload["fault_code"] = validated[0] if validated else ""
    try:
        entry = RuleStore().upsert(payload, saved_by=saved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out: dict[str, Any] = {"ok": True, "rule": entry}
    if fault_inference:
        out["fault_inference"] = fault_inference
    return out


@router.get("/saved/{rule_id}/source")
def get_rule_source(rule_id: str, _user: dict = Depends(require_user)) -> dict:
    rule = RuleStore().get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"rule not found: {rule_id}")
    path = str(rule.get("source_path") or "")
    code = str(rule.get("code") or "")
    if not code.strip() and path:
        code = read_source(path)
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


@router.get("/assignments")
def list_rule_assignments(
    site_id: str | None = None,
    _user: dict = Depends(require_user),
) -> dict:
    svc = ModelService()
    ttl = TtlService()
    sid = (site_id or "").strip() or ensure_default_site(svc, ttl)
    model = svc.load()
    rules = RuleStore().list_rules()
    view = build_assignments_view(model, rules, site_id=sid)
    return {"ok": True, **view}


@router.post("/bind")
def patch_rule_binding(
    body: RuleBindOpBody,
    user: dict = Depends(require_roles("integrator", "agent", "operator")),
) -> dict:
    store = RuleStore()
    rule = store.get(body.rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"rule not found: {body.rule_id}")
    kind = body.kind  # validated by pattern
    op = body.op
    bindings = apply_bind_op(
        rule,
        op=op,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        target_id=body.target_id.strip(),
        point_ids=body.point_ids,
    )
    entry = store.upsert(
        {**rule, "bindings": bindings},
        saved_by=str(user.get("sub") or "operator"),
    )
    return {"ok": True, "rule": entry}


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
                "direct_point_ids": body.direct_point_ids
                if body.direct_point_ids is not None
                else body.point_ids,
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
    return run_batch(
        limit=body.limit,
        chunk_hours=body.chunk_hours,
        lookback_hours=body.lookback_hours,
        use_chunks=body.use_chunks,
    )


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
