"""Environment-driven config for the cloud exporter sidecar."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ExporterConfig:
    bridge_base_url: str
    export_endpoint: str
    interval_seconds: int
    dry_run: bool
    token: str
    site_id: str
    include_readings: bool
    include_faults: bool
    include_model_summary: bool
    max_points: int
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "ExporterConfig":
        return cls(
            bridge_base_url=os.environ.get("OPENFDD_BRIDGE_BASE_URL", "http://bridge:8765").strip(),
            export_endpoint=os.environ.get("OPENFDD_EXPORT_ENDPOINT", "").strip(),
            interval_seconds=max(30, int(os.environ.get("OPENFDD_EXPORT_INTERVAL_SECONDS", "300") or "300")),
            dry_run=_truthy(os.environ.get("OPENFDD_EXPORT_DRY_RUN"), default=True),
            token=os.environ.get("OPENFDD_EXPORT_TOKEN", "").strip(),
            site_id=os.environ.get("OPENFDD_EXPORT_SITE_ID", "").strip(),
            include_readings=_truthy(os.environ.get("OPENFDD_EXPORT_INCLUDE_READINGS"), default=True),
            include_faults=_truthy(os.environ.get("OPENFDD_EXPORT_INCLUDE_FAULTS"), default=True),
            include_model_summary=_truthy(os.environ.get("OPENFDD_EXPORT_INCLUDE_MODEL_SUMMARY"), default=False),
            max_points=max(1, int(os.environ.get("OPENFDD_EXPORT_MAX_POINTS", "100") or "100")),
            timeout_seconds=float(os.environ.get("OPENFDD_EXPORT_TIMEOUT_SECONDS", "20") or "20"),
        )

    def redacted(self) -> dict[str, str | int | bool]:
        return {
            "bridge_base_url": "redacted/local",
            "export_endpoint": self._redact_url(self.export_endpoint),
            "interval_seconds": self.interval_seconds,
            "dry_run": self.dry_run,
            "token": "***" if self.token else "",
            "site_id": self.site_id or "(unset)",
            "include_readings": self.include_readings,
            "include_faults": self.include_faults,
            "include_model_summary": self.include_model_summary,
            "max_points": self.max_points,
            "timeout_seconds": self.timeout_seconds,
        }

    @staticmethod
    def _redact_url(url: str) -> str:
        if not url:
            return ""
        if "://" in url:
            scheme, rest = url.split("://", 1)
            if "@" in rest:
                rest = rest.split("@", 1)[1]
            return f"{scheme}://***"
        return "***"
