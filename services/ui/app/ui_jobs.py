"""Thin Streamlit Jobs entry — prefers central `/api/jobs`, falls back to local job_store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from app import central_client, job_store


def _ws() -> Path:
    return job_store.workspace_root()


def _meta_from_api(job: dict[str, Any]) -> job_store.JobMeta:
    return job_store.JobMeta.from_dict(job)


def _list_active_jobs() -> tuple[list[job_store.JobMeta], str | None]:
    """Returns (jobs, error_or_None). Prefer central; fall back to filesystem."""
    if central_client.health_ok():
        resp = central_client.jobs_list(include_archived=False)
        if resp.get("ok") and isinstance(resp.get("jobs"), list):
            out = []
            for raw in resp["jobs"]:
                if isinstance(raw, dict):
                    try:
                        out.append(_meta_from_api(raw))
                    except ValueError:
                        continue
            return out, None
        if resp.get("central_down"):
            pass  # fall through
        elif resp.get("error"):
            return [], str(resp.get("error"))
    try:
        return job_store.list_jobs(ws=_ws(), include_archived=False), None
    except OSError as exc:
        return [], str(exc)


def _apply_job_to_session(meta: job_store.JobMeta, mapping: dict[str, Any] | None) -> None:
    st.session_state["openfdd_job_id"] = meta.job_id
    st.session_state["openfdd_job_name"] = meta.job_name
    st.session_state["openfdd_job_status"] = meta.status
    st.session_state["openfdd_job_meta_revision"] = meta.meta_revision
    if meta.latest_run_id:
        st.session_state["openfdd_latest_run_id"] = meta.latest_run_id
    if meta.site_name:
        st.session_state["site_id"] = meta.site_name
    if meta.building_name:
        st.session_state["building_id"] = meta.building_name
    if mapping is not None:
        st.session_state["role_map"] = mapping


def render_jobs_sidebar() -> None:
    """Sidebar expander: list / create / open / archive Jobs."""
    with st.sidebar.expander("Jobs (persistent)", expanded=False):
        st.caption(
            "Analysis Jobs under `workspace/jobs/` via central `/api/jobs` when available "
            "(local filesystem fallback). Not `st.session_state`."
        )
        jobs, err = _list_active_jobs()
        if err:
            st.warning(f"Jobs unavailable: {err}")
            return

        current = st.session_state.get("openfdd_job_id")
        if current:
            st.success(f"Open: `{st.session_state.get('openfdd_job_name') or current}`")
            stale = st.session_state.get("openfdd_run_stale_reasons")
            if stale:
                st.warning("Run stale: " + ", ".join(stale))

        labels = [f"{j.job_name} ({j.job_id[-12:]})" for j in jobs]
        id_by_label = {f"{j.job_name} ({j.job_id[-12:]})": j.job_id for j in jobs}

        if labels:
            pick = st.selectbox("Open job", ["(none)"] + labels, key="jobs_pick")
            if pick != "(none)" and st.button("Open selected", key="jobs_open_btn"):
                jid = id_by_label[pick]
                try:
                    meta = None
                    if central_client.health_ok():
                        resp = central_client.jobs_get(jid)
                        if resp.get("ok") and isinstance(resp.get("job"), dict):
                            meta = _meta_from_api(resp["job"])
                    if meta is None:
                        meta = job_store.load_job(jid, ws=_ws())
                    mapping = None
                    try:
                        mapping = job_store.load_mapping(jid, ws=_ws())
                    except FileNotFoundError:
                        mapping = None
                    _apply_job_to_session(meta, mapping)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
        else:
            st.caption("No active jobs yet.")

        st.markdown("**New job**")
        name = st.text_input("Job name", key="jobs_new_name", placeholder="e.g. Building 100 RCx")
        if st.button("Create job", key="jobs_create_btn", disabled=not (name or "").strip()):
            try:
                meta = None
                if central_client.health_ok():
                    resp = central_client.jobs_create(
                        name.strip(),
                        site_name=st.session_state.get("site_id"),
                        building_name=st.session_state.get("building_id"),
                    )
                    if resp.get("ok") and isinstance(resp.get("job"), dict):
                        meta = _meta_from_api(resp["job"])
                if meta is None:
                    meta = job_store.create_job(
                        name.strip(),
                        site_name=st.session_state.get("site_id"),
                        building_name=st.session_state.get("building_id"),
                        ws=_ws(),
                    )
                role_map = st.session_state.get("role_map")
                if isinstance(role_map, dict) and role_map:
                    job_store.save_mapping(meta.job_id, role_map, ws=_ws())
                    meta = job_store.load_job(meta.job_id, ws=_ws())
                _apply_job_to_session(
                    meta,
                    role_map if isinstance(role_map, dict) else None,
                )
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))

        if current and st.button("Save mapping to job", key="jobs_save_map_btn"):
            role_map = st.session_state.get("role_map")
            if not isinstance(role_map, dict) or not role_map:
                st.warning("No role_map in session to save.")
            else:
                try:
                    job_store.save_mapping(current, role_map, ws=_ws())
                    st.success("Mapping saved to job.")
                except (ValueError, OSError) as exc:
                    st.error(str(exc))

        if current and st.button("Archive open job", key="jobs_archive_btn"):
            try:
                archived = False
                if central_client.health_ok():
                    resp = central_client.jobs_archive(current)
                    if resp.get("ok"):
                        archived = True
                    elif not resp.get("central_down"):
                        st.error(str(resp.get("error") or "archive failed"))
                        return
                if not archived:
                    job_store.archive_job(current, ws=_ws())
                st.session_state.pop("openfdd_job_id", None)
                st.session_state.pop("openfdd_job_name", None)
                st.session_state.pop("openfdd_job_status", None)
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))
