"""In-product ECM package agent-build entry (OFDD-076 / OFDD-072).

Creates a job-native **ECM package request** from the active Job/site. The heavy
agent-build (Excel workbook + notebook) and any EnergyPlus/IDF calibration are
**delegated** to WattLab / the external EnergyPlus runner — open-fdd central never
parses IDF or runs E+ in-process.

Two agent-build paths, in order of preference:

1. **WattLab notebook builder** when a ``wattlab`` CLI / module is installed (the
   request records the shell-out target for pickup).
2. Otherwise a placeholder ECM package request JSON under the job's
   ``wattlab/ecm/`` with ``honesty.openfdd = "delegated"`` when
   ``open_fdd.ecm_engineering`` imports (``"unavailable"`` when it does not).

**cascade-if-ready:** when a Docker socket **and** an ``energyplus-mcp-dev`` image
are present, an external EnergyPlus run is queued via the existing central
``/api/jobs/{id}/eplus/runs`` (QUEUED metadata only). Otherwise an honest
ESCO/ECM-screening-only stamp is recorded — no fabricated calibrated compare.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from typing import Any

import streamlit as st

from app import central_client, job_store

_TRUTHY = {"1", "true", "yes", "on"}


def ecm_engineering_available() -> bool:
    """True when ``open_fdd.ecm_engineering`` (ECM workbook toolkit) is importable."""
    try:
        return importlib.util.find_spec("open_fdd.ecm_engineering") is not None
    except Exception:
        return False


def ecm_engineering_version() -> str | None:
    try:
        import open_fdd.ecm_engineering as ecm

        return getattr(ecm, "__version__", None)
    except Exception:
        return None


def wattlab_agent_build_available() -> str | None:
    """Detect a WattLab agent-build entry (env override, CLI, or importable module)."""
    env = (os.environ.get("OPENFDD_WATTLAB_CLI") or "").strip()
    if env:
        return env
    found = shutil.which("wattlab")
    if found:
        return found
    try:
        if importlib.util.find_spec("wattlab") is not None:
            return "wattlab (module)"
    except Exception:
        pass
    return None


def _energyplus_mcp_present() -> bool:
    """Honest detection of an ``energyplus-mcp-dev`` runner (env-gated, no fabrication)."""
    if (os.environ.get("OPENFDD_ENERGYPLUS_MCP") or "").strip().lower() in _TRUTHY:
        return True
    return bool((os.environ.get("OPENFDD_ENERGYPLUS_MCP_IMAGE") or "").strip())


def _docker_sock_present() -> bool:
    if (os.environ.get("DOCKER_HOST") or "").strip():
        return True
    sock = (os.environ.get("OPENFDD_DOCKER_SOCK") or "/var/run/docker.sock").strip()
    try:
        return os.path.exists(sock)
    except OSError:
        return False


def cascade_readiness() -> dict[str, Any]:
    """cascade-if-ready gate: both docker.sock and energyplus-mcp-dev must be present."""
    has_sock = _docker_sock_present()
    has_mcp = _energyplus_mcp_present()
    reasons: list[str] = []
    if not has_sock:
        reasons.append("no docker.sock / DOCKER_HOST")
    if not has_mcp:
        reasons.append("energyplus-mcp-dev not detected (set OPENFDD_ENERGYPLUS_MCP)")
    return {
        "docker_sock": has_sock,
        "energyplus_mcp": has_mcp,
        "ready": has_sock and has_mcp,
        "reasons": reasons,
    }


def build_ecm_package_request(
    *,
    job_id: str,
    building_id: str,
    run_id: str | None = None,
    findings_revision: str | None = None,
    notes: str | None = None,
    ecm_available: bool | None = None,
    wattlab_cli: str | None = None,
    cascade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape the ECM package request payload (pure — no I/O). Honesty-first."""
    if ecm_available is None:
        ecm_available = ecm_engineering_available()
    honesty_state = "delegated" if ecm_available else "unavailable"
    return {
        "kind": "ecm_package_request",
        "source": "openfdd_ui",
        "job_id": job_id,
        "building_id": building_id or None,
        "run_id": run_id,
        "findings_revision": findings_revision,
        "engine": {
            "open_fdd_ecm_engineering": bool(ecm_available),
            "open_fdd_ecm_engineering_version": ecm_engineering_version() if ecm_available else None,
            "wattlab_agent_build": wattlab_cli or None,
        },
        "honesty": {
            "openfdd": honesty_state,
            "detail": (
                "ECM package agent-build (Excel workbook + notebook) and any "
                "EnergyPlus/IDF calibration are delegated to WattLab / the external "
                "EnergyPlus runner. open-fdd central never parses IDF or runs E+."
            ),
        },
        "cascade": cascade or {},
        "notes": notes,
    }


def maybe_cascade_eplus(
    job_id: str,
    *,
    model_ref: str | None = None,
    handoff_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Queue an external E+ run via central when ready; else return an honesty stamp."""
    readiness = cascade_readiness()
    if not readiness["ready"]:
        return {
            "ok": False,
            "cascaded": False,
            "readiness": readiness,
            "honesty": "esco_screening_only",
            "detail": (
                "cascade-if-ready gate not satisfied; ESCO/ECM screening only "
                "(no calibrated EnergyPlus compare)."
            ),
        }
    run: dict[str, Any] = {}
    if model_ref:
        run["model_ref"] = model_ref
    if handoff_id:
        run["handoff_id"] = handoff_id
    if notes:
        run["notes"] = notes
    resp = central_client.jobs_queue_eplus_run(job_id, run)
    cascaded = bool(resp.get("ok"))
    return {
        "ok": cascaded,
        "cascaded": cascaded,
        "readiness": readiness,
        "response": resp,
        "honesty": "delegated_external_runner" if cascaded else "queue_failed",
    }


def create_ecm_package_request(
    job_id: str,
    *,
    building_id: str,
    run_id: str | None = None,
    findings_revision: str | None = None,
    notes: str | None = None,
    do_cascade: bool = False,
    model_ref: str | None = None,
    handoff_id: str | None = None,
    ws: Any | None = None,
) -> dict[str, Any]:
    """Write a job-native ECM package request (and optionally queue an E+ cascade)."""
    ecm_available = ecm_engineering_available()
    wattlab = wattlab_agent_build_available()
    cascade_result = (
        maybe_cascade_eplus(job_id, model_ref=model_ref, handoff_id=handoff_id, notes=notes)
        if do_cascade
        else None
    )
    request = build_ecm_package_request(
        job_id=job_id,
        building_id=building_id,
        run_id=run_id,
        findings_revision=findings_revision,
        notes=notes,
        ecm_available=ecm_available,
        wattlab_cli=wattlab,
        cascade=cascade_result or cascade_readiness(),
    )
    path = job_store.save_ecm_request(job_id, request, ws=ws)
    return {"ok": True, "path": str(path), "request": request, "cascade": cascade_result}


def discover_wattlab_xlsx(ws: Any | None = None) -> list[str]:
    """Find agent-built ECM workbooks under the WattLab workspace (honest handoff)."""
    roots: list[Any] = []
    env = (os.environ.get("OPENFDD_WATTLAB_WORKSPACE") or os.environ.get("WATTLAB_WORKSPACE") or "").strip()
    if env:
        roots.append(env)
    if ws is not None:
        roots.append(ws)
    # Common lab bind: sibling wattlab_workspace next to OPENFDD_WORKSPACE
    ofdd_ws = (os.environ.get("OPENFDD_WORKSPACE") or "").strip()
    if ofdd_ws:
        roots.append(os.path.join(os.path.dirname(ofdd_ws), "wattlab_workspace"))
        roots.append(os.path.join(ofdd_ws, "wattlab"))
    found: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root:
            continue
        base = os.path.join(str(root), "reports", "notebooks")
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if not name.lower().endswith(".xlsx"):
                    continue
                path = os.path.join(dirpath, name)
                if path in seen:
                    continue
                seen.add(path)
                found.append(path)
    found.sort()
    return found[:40]


def render_ecm_agent_build_panel() -> None:
    """Streamlit panel: create an ECM package request from the active Job/site."""
    st.markdown("##### ECM package (agent-build)")
    st.info(
        "**Gate C honesty:** open-fdd records the ECM package **request** only. "
        "The real Excel workbook (`.xlsx` / `FORMULA_ESCO_*` / full-parity book) is built in "
        "**vibe20** via `wattlab notebook agent-build`. open-fdd is not vibe20-complete for spreadsheets."
    )
    st.caption(
        "Create an ECM Excel/notebook package request from the active Job. Heavy "
        "agent-build + EnergyPlus/IDF stay delegated to WattLab / the external E+ "
        "runner — open-fdd central never parses IDF."
    )
    job_id = st.session_state.get("openfdd_job_id")
    if not job_id:
        st.info("Open or create a Job (sidebar → Jobs) from the active site to build an ECM package.")
        return

    if ecm_engineering_available():
        ver = ecm_engineering_version() or "?"
        st.caption(f"`open_fdd.ecm_engineering` v{ver} present → `honesty.openfdd = delegated`.")
    else:
        st.caption(
            "`open_fdd.ecm_engineering` not installed → `honesty.openfdd = unavailable` "
            "(request still recorded for pickup)."
        )

    wattlab = wattlab_agent_build_available()
    if wattlab:
        st.caption(f"WattLab agent-build detected: `{wattlab}` (notebook builder path).")
    else:
        st.caption(
            "WattLab agent-build CLI not detected — request is recorded for later pickup. "
            "Run vibe20: `wattlab notebook agent-build --out reports/notebooks …`."
        )

    xlsx_hits = discover_wattlab_xlsx()
    if xlsx_hits:
        with st.expander(f"Found {len(xlsx_hits)} WattLab ECM workbook(s) (download handoff)", expanded=False):
            for path in xlsx_hits:
                st.code(path, language=None)
    else:
        st.caption(
            "No `reports/notebooks/**/*.xlsx` found under WattLab workspace yet — "
            "build in vibe20, then refresh this panel."
        )
    readiness = cascade_readiness()
    if readiness["ready"]:
        st.success(
            "cascade-if-ready: docker.sock + energyplus-mcp-dev present → "
            "external E+ compare can be queued."
        )
    else:
        st.warning(
            "cascade-if-ready gate not met ("
            + "; ".join(readiness["reasons"])
            + ") → ESCO/ECM screening only."
        )

    notes = st.text_input("Notes", key="ecm_job_notes")
    model_ref = st.text_input(
        "E+ model ref (relative path under job, optional)", key="ecm_job_model_ref"
    )
    do_cascade = st.checkbox(
        "Queue EnergyPlus cascade when ready",
        value=bool(readiness["ready"]),
        key="ecm_job_cascade",
    )

    if st.button("Create ECM package request", key="ecm_job_create", type="primary"):
        try:
            result = create_ecm_package_request(
                str(job_id),
                building_id=(st.session_state.get("building_id") or ""),
                run_id=st.session_state.get("openfdd_latest_run_id"),
                findings_revision=st.session_state.get("openfdd_findings_revision"),
                notes=notes or None,
                do_cascade=bool(do_cascade),
                model_ref=(model_ref.strip() or None),
            )
        except Exception as exc:  # keep the Export tab alive on failure
            st.error(f"ECM package request failed: {exc}")
            return
        st.success(f"ECM package request written: `{result['path']}`")
        cascade = result.get("cascade")
        if cascade:
            if cascade.get("cascaded"):
                st.success("Queued external EnergyPlus run (cascade-if-ready).")
            else:
                st.info("Cascade not queued: " + (cascade.get("detail") or "gate not satisfied"))
        st.session_state["openfdd_last_ecm_request"] = result["request"]
        st.json(result["request"])
