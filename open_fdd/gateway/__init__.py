"""FastAPI HTTP gateway (bridge) for local Open-FDD desktop stack."""

from open_fdd.gateway.openclaw_chat import OpenClawChatResponse, OpenClawGatewayChatClient
from open_fdd.gateway.cli import run_desktop_bridge, run_gateway
from open_fdd.gateway.server import create_app

__all__ = [
    "OpenClawChatResponse",
    "OpenClawGatewayChatClient",
    "create_app",
    "run_desktop_bridge",
    "run_gateway",
]
