from __future__ import annotations


class McpError(Exception):
    """Structured MCP tool error (returned to clients as message text)."""


class HumanApprovalRequired(McpError):
    def __init__(self, action: str) -> None:
        super().__init__(
            f"{action} requires human_approved=true. "
            "A human operator must review the change before it is applied."
        )
