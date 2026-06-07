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


def require_bacnet_poll_config(user: dict = Depends(require_user)) -> dict:
    """Enable/disable poll intervals on known points — any authenticated OT role."""
    role = user.get("role")
    if role in ("operator", "integrator", "agent"):
        return user
    raise HTTPException(status_code=403, detail="forbidden")


def _bacnet_mutation_denial_detail(role: str | None) -> dict[str, str]:
    """Human-readable 403 payload for driver/model registry writes."""
    flag_on = bacnet_discovery_mutations_enabled()
    if role not in ("integrator", "agent"):
        return {
            "code": "bacnet_mutations_role",
            "message": "Adding BACnet devices to the driver registry requires the integrator account.",
            "hint": "Sign out and sign in with OFDD_INTEGRATOR_USER from workspace/auth.env.local.",
        }
    if role == "agent" and not agent_can_bacnet_mutate():
        return {
            "code": "bacnet_mutations_role",
            "message": "Agent accounts cannot update the BACnet driver registry on this server.",
            "hint": "Sign in as integrator or set OFDD_AGENT_CAN_BACNET_MUTATE=1 (automation only).",
        }
    if not flag_on:
        return {
            "code": "bacnet_mutations_disabled",
            "message": "Driver registry updates are disabled on this bridge (point discovery still works).",
            "hint": "Remove OFDD_DISABLE_BACNET_DISCOVERY_MUTATIONS or set OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS=1, then recreate the bridge container (docker compose up -d --force-recreate bridge).",
        }
    return {
        "code": "bacnet_mutations_denied",
        "message": "BACnet driver registry update not permitted.",
        "hint": "",
    }


def require_bacnet_mutation(request: Request, user: dict = Depends(require_user)) -> dict:
    role = user.get("role")
    allowed = False
    if role == "integrator" and bacnet_discovery_mutations_enabled():
        allowed = True
    elif role == "agent" and agent_can_bacnet_mutate() and bacnet_discovery_mutations_enabled():
        allowed = True
    if allowed:
        return user
    denial = _bacnet_mutation_denial_detail(role)
    write_audit(
        event_type="bacnet.command",
        action="mutation denied",
        outcome="failure",
        severity="warning",
        request=request,
        user=user,
        resource_type="bacnet",
        detail={"role": role, "code": denial.get("code"), "reason": denial.get("message")},
    )
    raise HTTPException(status_code=403, detail=denial)
