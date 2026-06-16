"""Building status family grouping from enriched FDD context."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.building_status import _family_label, _family_of  # noqa: E402


def test_family_of_uses_model_context_equipment():
    alert = {
        "source": "fdd",
        "model_context": {
            "equipment": {"id": "vav-12", "name": "VAV-12", "type": "Variable_Air_Volume_Box"},
        },
    }
    assert _family_of(alert) == "EQ:vav-12"
    assert _family_label(_family_of(alert), [alert]).lower() == "vav-12"


def test_family_of_not_general_when_context_has_name_only():
    alert = {
        "source": "fdd",
        "model_context": {"equipment": {"id": "", "name": "RTU-1", "type": "AHU"}},
    }
    assert _family_of(alert) == "EQ:RTU-1"
