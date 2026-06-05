"""BACnet route role gates (read vs discovery vs mutation)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .audit import write_audit
from .deps import require_user
from .security import (
    agent_can_bacnet_mutate,
    bacnet_discovery_mutations_enabled,
    operator_can_bacnet_discover,
)


def require_bacnet_discovery(user: dict = Depends(require_user)) -> dict:
    role = user.get("role")
    if role in ("integrator", "agent"):
        return user
    if role == "operator" and operator_can_bacnet_discover():
        return user
    raise HTTPException(status_code=403, detail="forbidden")


def require_bacnet_mutation(request: Request, user: dict = Depends(require_user)) -> dict:
    role = user.get("role")
    allowed = False
    if role == "integrator" and bacnet_discovery_mutations_enabled():
        allowed = True
    elif role == "agent" and agent_can_bacnet_mutate() and bacnet_discovery_mutations_enabled():
        allowed = True
    if allowed:
        return user
    write_audit(
        event_type="bacnet.command",
        action="mutation denied",
        outcome="failure",
        severity="warning",
        request=request,
        user=user,
        resource_type="bacnet",
        detail={"role": role, "reason": "BACnet mutations require integrator and OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS"},
    )
    raise HTTPException(
        status_code=403,
        detail="BACnet model/driver mutations require integrator role and OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS=1",
    )
