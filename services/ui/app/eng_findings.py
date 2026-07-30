"""Engineering Findings panel (OFDD-074 / OFDD-069).

Replaces the Overview "Generic RCx DOCX" template as the Engineering Findings
story. Detection ≠ finding: rule hits are *candidates* until deterministic
evidence review.

Primary path: the ``open_fdd.reporting`` HITL pipeline over the **active site's**
rule results (``st.session_state.batch_results``) → prioritized findings +
DOCX / XLSX / JSON artifacts.

Fallback path: when ``open_fdd.reporting`` is not in the installed package
(older PyPI ``open-fdd``), surface central ``/api/reports`` endpoints instead of
the retired static DOCX template.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from app import central_client

_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
}


def reporting_available() -> bool:
    """True when ``open_fdd.reporting`` (HITL Engineering Findings) is importable."""
    try:
        import open_fdd.reporting  # noqa: F401
    except Exception:
        return False
    return True


def _safe_name(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (s or ""))[:80] or "Building"


def _split_refs(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tok.strip() for tok in str(raw).replace("\n", ",").split(",") if tok.strip()]


def _parse_notes(raw: str | None) -> dict[str, str]:
    """Parse ``REF=note`` lines into a HITL notes dict (blank/invalid lines ignored)."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for line in str(raw).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        ref, note = line.split("=", 1)
        ref = ref.strip()
        note = note.strip()
        if ref and note:
            out[ref] = note
    return out


def _analysis_period_from_session() -> str:
    start = st.session_state.get("dataset_start_str") or st.session_state.get("dataset_start")
    end = st.session_state.get("dataset_end_str") or st.session_state.get("dataset_end")
    if start and end:
        return f"{start} → {end}"
    return ""


def _overview_context_from_session() -> dict[str, Any] | None:
    ctx = st.session_state.get("overview_context")
    return ctx if isinstance(ctx, dict) else None


def build_findings(
    results: list,
    *,
    building: str,
    analysis_period: str = "",
    overview_context: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    max_findings: int = 7,
    pin: list[str] | None = None,
    drop: list[str] | None = None,
    notes: dict[str, str] | None = None,
):
    """Run the ``open_fdd.reporting`` HITL pipeline over rule results.

    ``results`` are ``open_fdd.rules.base.RuleResult`` objects (the UI's
    ``batch_results`` are exactly this type via the ``app.rules.base`` shim), so
    they feed ``candidates_from_rule_results`` directly. Returns ``ReportArtifacts``.
    """
    from open_fdd.reporting import build_engineering_findings

    return build_engineering_findings(
        building=building,
        analysis_period=analysis_period,
        rule_results=list(results),
        context=context,
        overview_context=overview_context,
        max_findings=int(max_findings),
        pin_findings=pin or None,
        drop_findings=drop or None,
        notes=notes or None,
    )


def render_findings_bytes(
    artifacts,
    *,
    basename: str | None = None,
    docx: bool = True,
    xlsx: bool = True,
) -> tuple[dict[str, bytes], str | None]:
    """Render artifacts to a temp dir and return ``({filename: bytes}, error_or_None)``.

    Partial outputs are still captured when an optional writer (python-docx /
    openpyxl) is missing, so the operator always gets at least the JSON findings.
    """
    from open_fdd.reporting import render_engineering_report

    files: dict[str, bytes] = {}
    err: str | None = None
    with tempfile.TemporaryDirectory(prefix="ofdd-eng-findings-") as td:
        tmp = Path(td)
        try:
            render_engineering_report(
                artifacts,
                tmp,
                docx=docx,
                json_out=True,
                charts=False,
                xlsx=xlsx,
                basename=basename,
            )
        except Exception as exc:  # keep partial JSON/XLSX outputs on writer errors
            err = str(exc)
        for p in sorted(tmp.glob("*")):
            if p.is_file():
                try:
                    files[p.name] = p.read_bytes()
                except OSError:
                    continue
    return files, err


def _render_findings_summary(art: dict[str, Any]) -> None:
    import pandas as pd

    metrics = art.get("metrics") or {}
    st.caption(
        f"{metrics.get('n_priority_findings', 0)} priority finding(s) · "
        f"{metrics.get('n_candidates', 0)} candidate(s) · "
        f"strong {metrics.get('n_strongly_supported', 0)} / "
        f"probable {metrics.get('n_probable', 0)} / "
        f"inconclusive {metrics.get('n_inconclusive', 0)}"
    )
    gate = art.get("quality_gate") or {}
    if gate and not gate.get("ok", True):
        st.warning("Quality gate flagged issues: " + ", ".join(str(x) for x in (gate.get("reasons") or [])))

    findings = [f for f in (art.get("findings") or []) if f.get("include_in_report", True)]
    if not findings:
        st.info("No findings met the evidence bar for this report.")
        return
    rows = [
        {
            "F-id": f.get("finding_id"),
            "priority": f.get("priority"),
            "title": f.get("title"),
            "classification": f.get("effective_classification") or f.get("classification"),
            "equipment": ", ".join(f.get("equipment_ids") or []),
            "rules": ", ".join(f.get("rule_ids") or []),
        }
        for f in findings
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch", height=min(360, 80 + 28 * len(df)))


def _render_findings_downloads(files: dict[str, bytes], *, key: str) -> None:
    if not files:
        return
    st.markdown("###### Download findings")
    for name in sorted(files):
        ext = name.rsplit(".", 1)[-1].lower()
        st.download_button(
            f"Download {name}",
            data=files[name],
            file_name=name,
            mime=_MIME.get(ext, "application/octet-stream"),
            key=f"{key}_dl_{name}",
            use_container_width=True,
        )


def _render_central_reports_fallback(*, building: str, key: str) -> None:
    st.caption(
        "`open_fdd.reporting` is not in this build — using central `/api/reports`. "
        "Install `open-fdd[reporting]` for the in-UI HITL findings pipeline."
    )
    if not central_client.health_ok():
        st.info(
            "Engineering Findings requires either `open_fdd.reporting` (not installed) "
            "or a reachable openfdd-central `/api/reports`."
        )
        return
    listing = central_client.reports_list()
    if listing.get("ok") is False:
        st.warning(f"Central reports unavailable: {listing.get('error') or 'error'}")
        return
    reports = listing.get("reports") or listing.get("items") or []
    if reports:
        import pandas as pd

        st.dataframe(pd.DataFrame(reports), hide_index=True, width="stretch")
    else:
        st.caption("No central report artifacts yet.")
    if st.button("Create central report draft", key=f"{key}_central_draft"):
        resp = central_client.reports_draft({"building": building, "kind": "engineering_findings"})
        if resp.get("ok") is False:
            st.error(resp.get("error") or "draft create failed")
        else:
            st.success("Central report draft created.")


def render_engineering_findings_panel(*, key: str = "overview_eng_findings") -> None:
    """Overview Engineering Findings story (retires the static Generic RCx DOCX)."""
    st.markdown("##### Engineering Findings")
    st.caption(
        "Detection ≠ finding: rule hits are candidates until deterministic evidence "
        "review (`open_fdd.reporting` HITL) → prioritized findings + DOCX/XLSX/JSON."
    )

    if not reporting_available():
        _render_central_reports_fallback(
            building=(st.session_state.get("building_id") or "").strip() or "BUILDING",
            key=key,
        )
        return

    results = st.session_state.get("batch_results") or []
    building = (st.session_state.get("building_id") or "").strip() or "BUILDING"
    if not results:
        st.info("Run Rules first — Engineering Findings reviews the active site's rule results.")
        return

    faults = [r for r in results if getattr(r, "status", "") == "FAULT"]
    st.caption(f"{len(faults)} FAULT candidate(s) across {len(results)} evaluations for `{building}`.")

    with st.expander("Findings review (HITL)", expanded=False):
        max_findings = st.number_input(
            "Max findings", min_value=1, max_value=30, value=7, step=1, key=f"{key}_max"
        )
        pin_raw = st.text_input(
            "Pin findings (comma refs: rule_id / equipment_id / F-id)", key=f"{key}_pin"
        )
        drop_raw = st.text_input("Drop findings (comma refs)", key=f"{key}_drop")
        notes_raw = st.text_area(
            "Engineer notes (one `REF=note` per line)", key=f"{key}_notes", height=80
        )
        want_docx = st.checkbox("Word (DOCX)", value=True, key=f"{key}_docx")
        want_xlsx = st.checkbox("Excel (XLSX)", value=True, key=f"{key}_xlsx")

    if st.button(
        "Generate Engineering Findings",
        key=f"{key}_gen",
        type="primary",
        disabled=not faults,
    ):
        with st.spinner("Building engineering findings…"):
            try:
                artifacts = build_findings(
                    results,
                    building=building,
                    analysis_period=_analysis_period_from_session(),
                    overview_context=_overview_context_from_session(),
                    max_findings=int(max_findings),
                    pin=_split_refs(pin_raw),
                    drop=_split_refs(drop_raw),
                    notes=_parse_notes(notes_raw),
                )
                files, err = render_findings_bytes(
                    artifacts,
                    basename=f"{_safe_name(building)}_Engineering_Findings",
                    docx=bool(want_docx),
                    xlsx=bool(want_xlsx),
                )
            except Exception as exc:  # surface to operator instead of crashing Overview
                st.error(f"Findings generation failed: {exc}")
                return
        st.session_state[f"{key}_artifacts"] = artifacts.to_dict()
        st.session_state[f"{key}_files"] = files
        if err:
            st.warning(f"Some artifacts skipped (optional writer missing): {err}")
        # OFDD-069: persist a central draft so GET /api/reports/engineering-findings works.
        try:
            from app import central_client

            draft = central_client.reports_draft(
                {
                    "building": building,
                    "kind": "engineering_findings",
                    "template_id": "engineering_findings",
                    "report_type": "engineering_findings",
                    "summary": artifacts.to_dict().get("summary")
                    if hasattr(artifacts, "to_dict")
                    else None,
                }
            )
            if draft.get("ok") is False:
                st.caption(f"Central findings draft not stored: {draft.get('error')}")
            else:
                st.caption("Central engineering_findings draft stored (GET /api/reports/engineering-findings).")
        except Exception as exc:
            st.caption(f"Central findings draft skipped: {exc}")

    art = st.session_state.get(f"{key}_artifacts")
    if isinstance(art, dict):
        _render_findings_summary(art)
        _render_findings_downloads(st.session_state.get(f"{key}_files") or {}, key=key)
