from __future__ import annotations

import json

from open_fdd.assistant.data_model_openclaw import (
    build_data_model_redesign_user_message,
    extract_import_shape_from_llm_output,
)


def test_extract_import_shape_bare_object() -> None:
    payload = {"sites": [{"id": "s1"}], "equipment": [], "points": []}
    out = extract_import_shape_from_llm_output(json.dumps(payload))
    assert out == payload


def test_extract_import_shape_wrapper() -> None:
    inner = {"sites": [{"id": "s1"}], "equipment": [], "points": []}
    wrapped = {"validation_notes": [], "import_ready_json": inner}
    out = extract_import_shape_from_llm_output(json.dumps(wrapped))
    assert out == inner


def test_extract_import_shape_fenced() -> None:
    inner = {"sites": [{"id": "s1"}], "equipment": [], "points": []}
    text = "Here:\n```json\n" + json.dumps(inner) + "\n```\n"
    out = extract_import_shape_from_llm_output(text)
    assert out == inner


def test_extract_import_from_copy_paste_file_sections() -> None:
    inner = {"sites": [{"id": "s1"}], "equipment": [], "points": []}
    text = """Intro prose here.

=== FILE: open_fdd_data_model_import_ready.json ===
""" + json.dumps(
        inner,
    ) + """

=== FILE: 01_plant_bounds.yaml ===
name: x
"""
    out = extract_import_shape_from_llm_output(text)
    assert out == inner


def test_build_user_message_includes_rules() -> None:
    model = {"sites": [], "equipment": [], "points": []}
    rules = [("a/b.yaml", "name: x\ntype: bounds\n")]
    msg = build_data_model_redesign_user_message(model, rules)
    assert "GET /model/export" in msg
    assert '"sites": []' in msg
    assert "a/b.yaml" in msg
    assert "name: x" in msg
