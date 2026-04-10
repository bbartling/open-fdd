"""API response schemas for capabilities, errors, events, faults, and jobs."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Job status values for API
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_FINISHED = "finished"
JOB_STATUS_FAILED = "failed"


# --- Capabilities ---


class CapabilityResponse(BaseModel):
    """GET /capabilities: version and feature flags."""

    version: str = Field(..., description="Package version")
    features: dict[str, bool] = Field(
        ...,
        description="Feature flags: websocket, fault_state, jobs, bacnet_write",
    )
    # Built-in LLM endpoints are not part of Open-FDD; use external tooling +
    # GET /model-context/docs and OpenAPI /docs for discovery.
    ai_available: bool = Field(
        False,
        description="Always false in core Open-FDD; use an external agent stack.",
    )
    ai_backend: Literal["disabled"] = Field(
        "disabled",
        description="Core API does not embed an LLM; value is always disabled.",
    )


# --- Uniform error schema ---


class ErrorDetail(BaseModel):
    """Nested error for 401/403/404 and other API errors."""

    code: str = Field(..., description="Machine-readable code")
    message: str = Field(..., description="Human-readable message")
    details: Optional[dict[str, Any]] = Field(
        None, description="Optional extra context"
    )


class ErrorResponse(BaseModel):
    """Top-level error envelope for all API errors."""

    error: ErrorDetail


# --- WebSocket / event bus ---


class EventEnvelope(BaseModel):
    """Server-sent event on WebSocket."""

    type: str = Field(..., description="Always 'event' for data events")
    topic: str = Field(..., description="e.g. fault.raised, crud.point.created")
    ts: str = Field(..., description="ISO8601 timestamp")
    correlation_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


# --- Fault state (for HA binary_sensors) ---


class FaultStateItem(BaseModel):
    """Single fault state: active or cleared. bacnet_device_id from points when available."""

    id: str
    site_id: str
    equipment_id: str
    fault_id: str
    active: bool
    last_changed_ts: datetime
    last_evaluated_ts: Optional[datetime] = None
    context: Optional[dict[str, Any]] = None
    bacnet_device_id: Optional[str] = None


class FaultDefinitionItem(BaseModel):
    """One row from fault_definitions (for HA labels)."""

    fault_id: str
    name: str
    description: Optional[str] = None
    severity: str = "warning"
    category: str = "general"
    equipment_types: Optional[list[str]] = None


# --- Jobs ---


class JobResponse(BaseModel):
    """GET /jobs/{job_id} response."""

    job_id: str
    job_type: str = Field(..., description="e.g. bacnet.discovery, fdd.run")
    status: str = Field(..., description="queued|running|finished|failed")
    created_at: str = Field(..., description="ISO8601")
    updated_at: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class JobCreateResponse(BaseModel):
    """POST /jobs/* response."""

    job_id: str
    status: str = "queued"
