"""Thin Streamlit Jobs entry — create / open / archive persistent analysis Jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from app import job_store


def _ws() -> Path:
    return job_store.workspace_root()


def _apply_job_to_session(meta: job_store.JobMeta, mapping: dict[str, Any] | None) -> None:
    st.session_state["openfdd_job_id"] = meta.job_id
    st.session_state["openfdd_job_name"] = meta.job_name
    st.session_state["openfdd_job_status"] = meta.status
    if meta.site_name:
        st.session_state["site_id"] = meta.site_name
    if meta.building_name:
        st.session_state["building_id"] = meta.building_name
    if mapping is not None:
        st.session_state["role_map"] = mapping


def render_jobs_sidebar() -> None:
    """Sidebar expander: list / create / open / archive Jobs under workspace/jobs/."""
    with st.sidebar.expander("Jobs (persistent)", expanded=False):
        st.caption(
            "Analysis Jobs live under `workspace/jobs/` — not `st.session_state`. "
            "Telemetry stays in Feather/parquet."
        )
        try:
            jobs = job_store.list_jobs(ws=_ws(), include_archived=False)
        except OSError as exc:
            st.warning(f"Jobs store unavailable: {exc}")
            return

        current = st.session_state.get("openfdd_job_id")
        if current:
            st.success(f"Open: `{st.session_state.get('openfdd_job_name') or current}`")

        labels = [f"{j.job_name} ({j.job_id[-12:]})" for j in jobs]
        id_by_label = {f"{j.job_name} ({j.job_id[-12:]})": j.job_id for j in jobs}

        if labels:
            pick = st.selectbox("Open job", ["(none)"] + labels, key="jobs_pick")
            if pick != "(none)" and st.button("Open selected", key="jobs_open_btn"):
                jid = id_by_label[pick]
                try:
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
                meta = job_store.create_job(
                    name.strip(),
                    site_name=st.session_state.get("site_id"),
                    building_name=st.session_state.get("building_id"),
                    ws=_ws(),
                )
                # Snapshot current role map if present
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
                job_store.archive_job(current, ws=_ws())
                st.session_state.pop("openfdd_job_id", None)
                st.session_state.pop("openfdd_job_name", None)
                st.session_state.pop("openfdd_job_status", None)
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))
