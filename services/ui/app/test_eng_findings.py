"""OFDD-074/069 — Engineering Findings panel helpers (mock streamlit).

Heavy pipeline (``open_fdd.reporting`` → pandas) is exercised in the reporting
package's own suite; here we cover the UI glue helpers that must be correct
regardless of whether the reporting extra is installed.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("streamlit", MagicMock())

from app import eng_findings  # noqa: E402


def test_split_refs_handles_commas_and_newlines() -> None:
    assert eng_findings._split_refs("FC1, VAV-1\nF01 ,") == ["FC1", "VAV-1", "F01"]
    assert eng_findings._split_refs("") == []
    assert eng_findings._split_refs(None) == []


def test_parse_notes_ref_equals_note() -> None:
    notes = eng_findings._parse_notes("F01=verify damper\n\nbad line\nFC1 = fan off ok")
    assert notes == {"F01": "verify damper", "FC1": "fan off ok"}


def test_reporting_available_is_bool() -> None:
    # Must never raise even when the reporting extra is absent.
    assert isinstance(eng_findings.reporting_available(), bool)


def test_safe_name() -> None:
    assert eng_findings._safe_name("Building 100 / RCx") == "Building_100___RCx"
    assert eng_findings._safe_name("") == "Building"
