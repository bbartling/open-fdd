from __future__ import annotations
from pathlib import Path
from typing import Any
import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from open_fdd.ecm_engineering import ECMJob

app = FastAPI(title="Open-FDD ECM Workbook Service")

class ECMRequest(BaseModel):
    name: str = "Open-FDD ECM Job"
    globals: dict[str, Any] = Field(default_factory=dict)
    ecms: list[dict[str, Any]] = Field(default_factory=list)

@app.post("/ecm-workbook")
def create_ecm_workbook(request: ECMRequest):
    output_dir = Path("/tmp/open_fdd_ecm")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{uuid.uuid4().hex}.xlsx"

    job = ECMJob(request.name, path=path)
    if request.globals:
        job.set_global(**request.globals)

    for ecm in request.ecms:
        job.add_ecm(ecm["name"], ecm.get("inputs", {}))

    job.save()

    safe_name = request.name.replace(" ", "_")
    return FileResponse(
        path,
        filename=f"{safe_name}_ECMs.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
