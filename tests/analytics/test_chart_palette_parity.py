"""Permanent lock: React plotlyTheme RAINBOW_PALETTE == open_fdd.analytics.charts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from open_fdd.analytics.charts import RAINBOW_PALETTE

ROOT = Path(__file__).resolve().parents[2]
REACT_THEME = ROOT / "frontend" / "web" / "src" / "api" / "plotlyTheme.ts"


def _react_rainbow_palette() -> list[str]:
    text = REACT_THEME.read_text(encoding="utf-8")
    # Match hex colors in order inside RAINBOW_PALETTE = [ ... ]
    m = re.search(r"RAINBOW_PALETTE:\s*string\[\]\s*=\s*\[(.*?)\];", text, re.S)
    assert m, "RAINBOW_PALETTE not found in plotlyTheme.ts"
    return re.findall(r'"(#[0-9a-fA-F]{6})"', m.group(1))


def test_rainbow_palette_matches_react_plotly_theme() -> None:
    react = _react_rainbow_palette()
    assert react == list(RAINBOW_PALETTE)
    assert len(react) == 12
    # Spot-check known SoT indices used by economizer overlay / motors
    assert react[0] == "#e11d48"
    assert react[5] == "#2563eb"
    assert react[11] == "#dc2626"


def test_charts_contract_json_loads() -> None:
    path = ROOT / "frontend" / "web" / "src" / "api" / "charts.contract.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["ruleResultChart"]["xaxis_title"] == "timestamp"
    assert "mech_cooling_oat_bins" in doc["overview_png_stems"]
