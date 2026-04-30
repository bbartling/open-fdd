"""Open-FDD Claw compatibility exports (OpenClaw-inspired naming)."""

from __future__ import annotations

from open_fdd.gateway.openclaw_routing import (
    DEFAULT_COMPLEX_BACKEND,
    DEFAULT_SIMPLE_BACKEND,
    OpenClawRouteDecision,
    OpenClawRoutePolicy,
    TaskClass,
    classify_task,
    decide_route,
    load_route_policy,
)

__all__ = [
    "DEFAULT_COMPLEX_BACKEND",
    "DEFAULT_SIMPLE_BACKEND",
    "OpenClawRouteDecision",
    "OpenClawRoutePolicy",
    "TaskClass",
    "classify_task",
    "decide_route",
    "load_route_policy",
]

