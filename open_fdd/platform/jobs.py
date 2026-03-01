"""In-memory job store and background execution for BACnet discovery and FDD run."""

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from open_fdd.platform.realtime import (
    emit,
    TOPIC_BACNET_DISCOVERY,
    TOPIC_FDD_RUN,
)

_JOB_STORE: dict[str, dict] = {}
_LOCK = threading.Lock()

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_type: str, payload: Optional[dict] = None) -> str:
    """Create a job record and return job_id."""
    job_id = str(uuid.uuid4())
    with _LOCK:
        _JOB_STORE[job_id] = {
            "job_id": job_id,
            "job_type": job_type,
            "status": STATUS_QUEUED,
            "created_at": _ts(),
            "updated_at": None,
            "result": None,
            "error": None,
            "payload": payload or {},
        }
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _LOCK:
        return dict(_JOB_STORE.get(job_id, {})) or None


def set_job_running(job_id: str) -> None:
    with _LOCK:
        if job_id in _JOB_STORE:
            _JOB_STORE[job_id]["status"] = STATUS_RUNNING
            _JOB_STORE[job_id]["updated_at"] = _ts()


def set_job_finished(job_id: str, result: Optional[dict] = None) -> None:
    with _LOCK:
        if job_id in _JOB_STORE:
            _JOB_STORE[job_id]["status"] = STATUS_FINISHED
            _JOB_STORE[job_id]["updated_at"] = _ts()
            _JOB_STORE[job_id]["result"] = result


def set_job_failed(job_id: str, error: str) -> None:
    with _LOCK:
        if job_id in _JOB_STORE:
            _JOB_STORE[job_id]["status"] = STATUS_FAILED
            _JOB_STORE[job_id]["updated_at"] = _ts()
            _JOB_STORE[job_id]["error"] = error


def run_bacnet_discovery_job(job_id: str, gateway_id: Optional[str], instance: dict) -> None:
    """Run BACnet discovery in a thread; emit events."""
    from open_fdd.platform.api.bacnet import (
        _resolve_gateway_url,
        _get_gateways_list,
        _post_rpc,
    )
    from open_fdd.platform.graph_model import update_bacnet_from_point_discovery, write_ttl_to_file

    url = _resolve_gateway_url(gateway_id) if gateway_id else None
    if not url:
        for g in _get_gateways_list():
            url = g.get("url")
            break
    if not url:
        set_job_failed(job_id, "No BACnet gateway URL")
        emit(TOPIC_BACNET_DISCOVERY + ".failed", {"job_id": job_id, "error": "No gateway URL"})
        return

    emit(TOPIC_BACNET_DISCOVERY + ".started", {"job_id": job_id, "gateway_id": gateway_id})
    set_job_running(job_id)
    try:
        result = _post_rpc(url, "client_point_discovery", {"instance": instance or {"device_instance": 3456789}})
        if not result.get("ok") or not result.get("body"):
            set_job_failed(job_id, result.get("body") or str(result))
            emit(TOPIC_BACNET_DISCOVERY + ".failed", {"job_id": job_id, "result": result})
            return
        res = result.get("body", {})
        rpc_result = res.get("result") if isinstance(res, dict) else res
        data = (rpc_result.get("data") or rpc_result) if isinstance(rpc_result, dict) else {}
        objs = data.get("objects") or []
        dev_inst = (instance or {}).get("device_instance", 3456789)
        addr = data.get("device_address") or ""
        dev_name = None
        for o in objs:
            if isinstance(o, dict) and (o.get("object_identifier") or "").startswith("device,"):
                dev_name = o.get("object_name") or o.get("name")
                break
        update_bacnet_from_point_discovery(dev_inst, addr, objs, device_name=dev_name)
        write_ok, write_err = write_ttl_to_file()
        set_job_finished(
            job_id,
            {"objects_count": len(objs), "write_ok": write_ok, "write_error": write_err},
        )
        emit(
            TOPIC_BACNET_DISCOVERY + ".finished",
            {"job_id": job_id, "objects_count": len(objs)},
        )
    except Exception as e:
        set_job_failed(job_id, str(e))
        emit(TOPIC_BACNET_DISCOVERY + ".failed", {"job_id": job_id, "error": str(e)})


def run_fdd_job(job_id: str) -> None:
    """Run FDD loop in a thread; emit events."""
    from open_fdd.platform.loop import run_fdd_loop

    emit(TOPIC_FDD_RUN + ".started", {"job_id": job_id})
    set_job_running(job_id)
    try:
        results = run_fdd_loop()
        set_job_finished(job_id, {"faults_written": len(results), "sites_processed": "see fdd_run_log"})
        emit(TOPIC_FDD_RUN + ".finished", {"job_id": job_id, "faults_written": len(results)})
    except Exception as e:
        set_job_failed(job_id, str(e))
        emit(TOPIC_FDD_RUN + ".failed", {"job_id": job_id, "error": str(e)})
