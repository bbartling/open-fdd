"""Streamlit helpers for the Generic RCx Word report download."""

from __future__ import annotations

import streamlit as st

from app.docx_report import GENERIC_RCX_DOCX, REPORTS_DIR, load_generic_rcx_report, report_path

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def report_download_button(
    filename: str,
    label: str,
    key: str,
    *,
    primary: bool = False,
    help: str | None = None,
    use_container_width: bool = True,
) -> bool:
    """Render a download button for a file under ``assets/reports``. Returns True if shown."""
    path = report_path(filename)
    if not path.is_file():
        st.warning(f"Report template is not available: `{filename}`")
        return False
    st.download_button(
        label=label,
        data=path.read_bytes(),
        file_name=filename,
        mime=MIME_DOCX,
        key=key,
        type="primary" if primary else "secondary",
        help=help or f"Serves `{filename}` from assets/reports.",
        use_container_width=use_container_width,
    )
    return True


def render_overview_rcx_download(*, key: str = "overview_generic_rcx_docx") -> bool:
    """Primary Overview download for the single Generic RCx Word template."""
    st.markdown("##### RCx report template")
    st.caption(
        f"Download the Generic RCx Word report (`{GENERIC_RCX_DOCX}`) from "
        f"`{REPORTS_DIR.name}/`. Replace the file in place to customize narrative/layout."
    )
    return report_download_button(
        filename=GENERIC_RCX_DOCX,
        label="Download Generic RCx Report (DOCX)",
        key=key,
        primary=True,
        help="Single committed Open-FDD Generic RCx Word template.",
    )


def generic_rcx_bytes_for_tests() -> bytes:
    return load_generic_rcx_report()
