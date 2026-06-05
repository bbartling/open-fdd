"""Model mutation role gates."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .audit import write_audit
from .deps import require_user
from .security import operator_can_edit_model


def require_model_mutation(request: Request, user: dict = Depends(require_user)) -> dict:
    role = user.get("role")
    if role == "integrator":
        return user
    if role in ("operator", "agent") and operator_can_edit_model():
        return user
    write_audit(
        event_type="model.write",
        action="mutation denied",
        outcome="failure",
        severity="warning",
        request=request,
        user=user,
        resource_type="model",
        detail={"role": role, "reason": "model mutations require integrator or OFDD_OPERATOR_CAN_EDIT_MODEL"},
    )
    raise HTTPException(
        status_code=403,
        detail="Model mutations require integrator role (or OFDD_OPERATOR_CAN_EDIT_MODEL=1)",
    )
