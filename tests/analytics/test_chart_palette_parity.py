"""Permanent lock: React plotlyTheme RAINBOW_PALETTE == open_fdd.analytics.charts.

Also locks Inspect title/axis mode and PNG stem vocabulary in charts.contract.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from open_fdd.analytics.charts import RAINBOW_PALETTE, equipment_inspection_chart

ROOT = Path(__file__).resolve().parents[2]
REACT_THEME = ROOT / "frontend" / "web" / "src" / "api" / "plotlyTheme.ts"
CONTRACT = ROOT / "frontend" / "web" / "src" / "api" / "charts.contract.json"


def _react_rainbow_palette() -> list[str]:
    text = REACT_THEME.read_text(encoding="utf-8")
    # Match hex colors in order inside RAINBOW_PALETTE = [ ... ]
    m = re.search(r"RAINBOW_PALETTE:\s*string\[\]\s*=\s*\[(.*?)\];", text, re.S)
    assert m, "RAINBOW_PALETTE not found in plotlyTheme.ts"
    return re.findall(r'"(#[0-9a-fA-F]{6})"', m.group(1))


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_rainbow_palette_matches_react_plotly_theme() -> None:
    react = _react_rainbow_palette()
    assert react == list(RAINBOW_PALETTE)
    assert len(react) == 12
    # Spot-check known SoT indices used by economizer overlay / motors
    assert react[0] == "#e11d48"
    assert react[5] == "#2563eb"
    assert react[11] == "#dc2626"


def test_charts_contract_json_loads() -> None:
    doc = _contract()
    assert doc["ruleResultChart"]["xaxis_title"] == "timestamp"
    assert "mech_cooling_oat_bins" in doc["overview_png_stems"]
    assert doc["inspectChart"]["axis_mode"] == "stacked_domains"
    assert doc["inspectChart"]["line_shape"] == "linear"
    assert "{equipment_id}" in doc["inspectChart"]["title_template"]


def test_png_stem_vocabulary_covers_overview_rcx() -> None:
    doc = _contract()
    vocab = doc["png_stem_vocabulary"]
    react_map = vocab["react_overview_rcx"]
    pypi_map = vocab["pypi_overview_export"]
    stems = set(doc["overview_png_stems"])
    for preset, stem in react_map.items():
        assert stem in stems or stem.endswith("_weekly"), preset
        assert stem  # non-empty
    assert react_map["economizer_delta"] == "economizer_free_cooling_delta"
    assert react_map["bas_vs_web_oat"] == "bas_vs_web_oat"
    assert vocab["react_overview_rcx_companion"]["bas_vs_web_oat"] == (
        "bas_web_oat_deviation_hist"
    )
    assert pypi_map["mech_cooling_oat_bins"].startswith("overview_")
    assert "fuel_summary_bullet" in vocab["fuel"]
    assert vocab["rcx_generic_prefix"] == "rcx_"


def test_equipment_inspection_chart_matches_react_contract() -> None:
    """PyPI inspect twin uses stacked domains + Inspection title (not subplot_titles)."""
    doc = _contract()
    insp = doc["inspectChart"]
    idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "sat": [55.0, 56.0, 57.0, 58.0],
            "fan_status": [1, 1, 0, 0],
        },
        index=idx,
    )
    fig = equipment_inspection_chart(df, equipment_id="AHU_1")
    assert fig is not None
    title = fig.layout.title.text if fig.layout.title else ""
    expected = insp["title_template"].replace("{equipment_id}", "AHU_1")
    assert title == expected
    # Domain axes (not make_subplots annotations / empty y titles)
    assert fig.layout.yaxis.title.text == "sat"
    assert fig.layout.yaxis2.title.text == "fan_status"
    assert fig.layout.yaxis.domain is not None
    assert fig.layout.yaxis2.domain is not None
    assert fig.layout.yaxis.domain[1] > fig.layout.yaxis2.domain[1]
    for tr in fig.data:
        assert tr.line.shape == insp["line_shape"]
        assert float(tr.line.width) == float(insp["line_width"])
    # No subplot_titles annotations from make_subplots
    anns = list(fig.layout.annotations or [])
    assert not any(
        getattr(a, "text", None) in ("sat", "fan_status") for a in anns
    )
