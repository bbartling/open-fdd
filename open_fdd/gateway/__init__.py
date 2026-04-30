"""FastAPI HTTP gateway (bridge) for local Open-FDD desktop stack."""

from open_fdd.gateway.openfdd_claw_chat import OpenClawChatResponse, OpenClawGatewayChatClient
from open_fdd.gateway.openfdd_claw_routing import (
    OpenClawRouteDecision,
    OpenClawRoutePolicy,
    classify_task,
    decide_route,
    load_route_policy,
)
from open_fdd.gateway.cli import run_desktop_bridge, run_gateway


def create_app():
    """Lazy import to avoid requiring desktop deps for package import."""
    from open_fdd.gateway.server import create_app as _create_app

    return _create_app()

__all__ = [
    "OpenClawChatResponse",
    "OpenClawGatewayChatClient",
    "OpenClawRouteDecision",
    "OpenClawRoutePolicy",
    "classify_task",
    "decide_route",
    "load_route_policy",
    "create_app",
    "run_desktop_bridge",
    "run_gateway",
]
