"""Authorization header for diy-bacnet-server JSON-RPC when a gateway API key is configured."""

from __future__ import annotations

import os


def bacnet_gateway_request_headers() -> dict[str, str]:
    """
    Return Authorization: Bearer ... when OFDD_BACNET_SERVER_API_KEY is set (stack/.env).

    diy-bacnet-server enables RPC protection when BACNET_RPC_API_KEY is set to the same value.
    """
    k = (os.environ.get("OFDD_BACNET_SERVER_API_KEY") or "").strip()
    if not k:
        return {}
    return {"Authorization": f"Bearer {k}"}
