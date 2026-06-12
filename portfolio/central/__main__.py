"""Run OpenFDD RCx Central API: python -m portfolio.central"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("OPENFDD_CENTRAL_API_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENFDD_CENTRAL_API_PORT", "8060"))
    uvicorn.run(
        "portfolio.central.api:app",
        host=host,
        port=port,
        reload=bool(os.environ.get("OPENFDD_CENTRAL_RELOAD")),
    )


if __name__ == "__main__":
    main()
