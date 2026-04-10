"""Jobs API: POST /jobs/bacnet/discovery, POST /jobs/fdd/run, GET /jobs/{job_id}."""

import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openfdd_stack.platform.api.schemas import JobResponse, JobCreateResponse
from openfdd_stack.platform import jobs as job_store

router = APIRouter(prefix="/jobs", tags=["jobs"])


class BacnetDiscoveryJobBody(BaseModel):
    """Body for POST /jobs/bacnet/discovery."""

    gateway_id: str | None = Field(None, description="From GET /bacnet/gateways")
    device_instance: int = Field(3456789, ge=0, le=4194303)


class FddRunJobBody(BaseModel):
    """Body for POST /jobs/fdd/run (optional params)."""

    pass


@router.post("/bacnet/discovery", response_model=JobCreateResponse)
def start_bacnet_discovery_job(body: BacnetDiscoveryJobBody | None = None):
    """
    Queue BACnet point discovery (same as POST /bacnet/point_discovery_to_graph but async).
    Returns job_id; poll GET /jobs/{job_id} or subscribe to bacnet.discovery.*.
    """
    body = body or BacnetDiscoveryJobBody()
    job_id = job_store.create_job("bacnet.discovery", body.model_dump())
    instance = {"device_instance": body.device_instance}
    thread = threading.Thread(
        target=job_store.run_bacnet_discovery_job,
        args=(job_id, body.gateway_id, instance),
        daemon=True,
    )
    thread.start()
    return JobCreateResponse(job_id=job_id, status=job_store.STATUS_QUEUED)


@router.post("/fdd/run", response_model=JobCreateResponse)
def start_fdd_run_job(body: FddRunJobBody | None = None):
    """
    Queue FDD rule run. Returns job_id; poll GET /jobs/{job_id} or subscribe to fdd.run.*.
    """
    job_id = job_store.create_job("fdd.run", {})
    thread = threading.Thread(target=job_store.run_fdd_job, args=(job_id,), daemon=True)
    thread.start()
    return JobCreateResponse(job_id=job_id, status=job_store.STATUS_QUEUED)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    """Get job status and result."""
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Job not found"})
    return JobResponse(
        job_id=job["job_id"],
        job_type=job["job_type"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job.get("updated_at"),
        result=job.get("result"),
        error=job.get("error"),
    )
