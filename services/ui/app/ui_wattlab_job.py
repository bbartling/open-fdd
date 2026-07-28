"""Job-native WattLab handoff UI — production SoT via central `/api/jobs/.../wattlab/handoffs`.

Zip dumps remain additive (Export → Build WattLab dump). Prefer this path when a Job is open.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app import central_client


def build_handoff_payload(
    *,
    job_id: str,
    run_id: str | None = None,
    findings_revision: str | None = None,
    profile: str = "summary",
    notes: str | None = None,
) -> dict[str, Any]:
    """Shape posted to ``jobs_create_wattlab_handoff`` (central persists under wattlab/handoffs/)."""
    payload: dict[str, Any] = {
        "schema_version": "1",
        "job_id": job_id,
        "source": "job_native",
        "profile": profile or "summary",
        "kind": "wattlab_handoff",
    }
    if run_id:
        payload["run_id"] = run_id
    if findings_revision:
        payload["findings_revision"] = findings_revision
    if notes:
        payload["notes"] = notes
    return payload


def create_job_native_handoff(
    job_id: str,
    *,
    run_id: str | None = None,
    findings_revision: str | None = None,
    profile: str = "summary",
    notes: str | None = None,
) -> dict[str, Any]:
    """POST job-native handoff via central_client. Returns central JSON dict."""
    handoff = build_handoff_payload(
        job_id=job_id,
        run_id=run_id,
        findings_revision=findings_revision,
        profile=profile,
        notes=notes,
    )
    return central_client.jobs_create_wattlab_handoff(job_id, handoff)


def render_job_native_wattlab_handoff() -> None:
    """Streamlit button: create handoff when a Job is open and central is reachable."""
    job_id = st.session_state.get("openfdd_job_id")
    st.markdown("##### Job-native WattLab handoff")
    st.caption(
        "Production source of truth is `workspace/jobs/<id>/wattlab/handoffs/*.json` "
        "via central. Zip dump below remains additive for offline / vibe20 backup."
    )
    if not job_id:
        st.info("Open a Job (sidebar) to create a job-native WattLab handoff.")
        return
    if not central_client.health_ok():
        st.warning("Central unavailable — job-native handoff requires `/api/jobs`.")
        return

    profile = st.selectbox(
        "Handoff profile",
        options=["summary", "diagnostic", "forensic"],
        key="wattlab_job_handoff_profile",
    )
    if st.button("Create job-native WattLab handoff", key="wattlab_job_handoff_btn"):
        resp = create_job_native_handoff(
            str(job_id),
            run_id=st.session_state.get("openfdd_latest_run_id"),
            findings_revision=st.session_state.get("openfdd_findings_revision"),
            profile=str(profile),
        )
        if resp.get("ok") and isinstance(resp.get("handoff"), dict):
            hid = resp["handoff"].get("handoff_id", "?")
            st.success(f"Handoff saved: `{hid}`")
            st.session_state["openfdd_last_wattlab_handoff"] = resp["handoff"]
        else:
            st.error(resp.get("error") or "handoff create failed")
