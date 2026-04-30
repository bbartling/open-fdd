from __future__ import annotations

from typing import TYPE_CHECKING, Any

from open_fdd.desktop.services.brick_service import BrickService
from open_fdd.desktop.services.ml_service import MLService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService

if TYPE_CHECKING:
    from open_fdd.desktop.services.ingest_service import IngestService

__all__ = ["BrickService", "IngestService", "MLService", "ModelService", "TtlService"]


def __getattr__(name: str) -> Any:
    """Lazy-load IngestService to break cycles with ``platform.drivers``."""
    if name == "IngestService":
        from open_fdd.desktop.services.ingest_service import IngestService as _IngestService

        return _IngestService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
