"""Plot spec: the Python producer against the golden files the JS producer is also tested against."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from open_fdd import plot_spec as ps  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "plot_spec"
DATA = ROOT / "open_fdd" / "data"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


MODEL = _json(FIX / "model.json")
CASES = _json(FIX / "cases.json")
SCHEMA = _json(DATA / "plot_spec.schema.json")
CATALOG = _json(DATA / "fdd-catalog.json")


def _equip(ref: str) -> dict:
    site, ident = ref.split("/")
    return next(e for e in MODEL["equips"] if e["attrs"]["siteRef"] == site and e["attrs"]["id"] == ident)


def _build(case: dict) -> dict:
    equips = [_equip(e) for e in case["equips"]]
    if case["kind"] == "rule":
        return ps.build_rule_spec(MODEL, case["id"], equips[0], CASES["window"])
    return ps.build_preset_spec(MODEL, case["id"], equips, CASES["window"])


def validate(value, schema, path="$"):
    """The draft 2020-12 subset plot_spec.schema.json uses (no third-party dependency)."""
    errs: list[str] = []
    if "$ref" in schema:
        return validate(value, SCHEMA["$defs"][schema["$ref"].split("/")[-1]], path)

    def kind(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "integer"
        return {list: "array", dict: "object", str: "string", float: "number"}[type(v)]

    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: not {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        want = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        k = kind(value)
        if not any(t == k or (t == "number" and k == "integer") for t in want):
            return errs + [f"{path}: type {k}, want {want}"]
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errs.append(f"{path}: pattern")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above maximum")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errs += validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        errs += [f"{path}: missing {r}" for r in schema.get("required", []) if r not in value]
        for k, v in value.items():
            if k in schema.get("properties", {}):
                errs += validate(v, schema["properties"][k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected {k}")
    return errs


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_golden(case):
    spec = _build(case)
    assert validate(spec, SCHEMA) == []
    try:
        import jsonschema as js  # optional: cross-check the subset validator against the real one
    except ImportError:
        js = None
    if js is not None:
        js.Draft202012Validator(SCHEMA).validate(spec)
    golden = (FIX / "golden" / f"{case['name']}.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert ps.to_json(spec) == golden
    assert ps.to_json(_build(case)) == ps.to_json(spec), "deterministic"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_producer_emits_the_same_bytes():
    script = (
        "const s=require('./nf-app/static/plot-spec.js'),fs=require('fs');"
        "const j=(p)=>JSON.parse(fs.readFileSync(p,'utf8'));"
        "const m=j('tests/fixtures/plot_spec/model.json'),c=j('tests/fixtures/plot_spec/cases.json'),cat=j('open_fdd/data/fdd-catalog.json');"
        "const eq=(r)=>{const [a,b]=r.split('/');return m.equips.find(e=>e.attrs.siteRef===a&&e.attrs.id===b)};"
        "const out=c.cases.map(k=>k.kind==='rule'?s.buildRuleSpec(m,k.id,eq(k.equips[0]),c.window,{catalog:cat}):"
        "s.buildPresetSpec(m,k.id,k.equips.map(eq),c.window,{catalog:cat})).map(s.toJson);"
        "process.stdout.write(JSON.stringify(out));"
    )
    res = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, check=True)
    js_out = json.loads(res.stdout.decode("utf-8"))
    assert js_out == [ps.to_json(_build(c)) for c in CASES["cases"]]


def test_briefed_cases():
    out = {c["name"]: _build(c) for c in CASES["cases"]}
    flow = out["rule-sv-range-chw-flow"]
    series = next(s for s in flow["series"] if s["role"] == "chw_flow")
    assert (series["quantity"], series["unit_si"]) == ("flow_water", "L/s")
    strip = next(s for s in flow["fault_strips"] if s["sensor_uuid"] == series["point_uuid"])
    assert strip["source"] == "timeline" and strip["approximate"] is False
    assert any(s["source"] == "intervals" and s["point_uuid"] is None for s in flow["fault_strips"])
    chw = out["rule-chw-1"]
    assert chw["fault_strips"][0]["source"] == "fault_pct" and chw["fault_strips"][0]["approximate"] is True
    assert chw["missing"] == [{"role": "chiller_power", "reason": "unit_unusable"}]
    assert out["rule-fc1"]["fault_strips"][0]["source"] == "timeline"
    unbound = out["preset-ahu-cooling-valves-unbound-by-alias"]
    assert unbound["missing"] == [{"role": "clg_valve_pct", "reason": "unbound"}] and unbound["preset_id"] == "ahu-cooling-valves"
    assert all(s["unit_si"] == "°C" for s in out["preset-ahu-dats-imperial-site"]["series"])


def test_color_key_is_fnv1a_mod_12():
    assert ps.color_key("") == 0x811C9DC5 % 12
    assert ps.color_key("a") == 0xE40C292C % 12
    for case in CASES["cases"]:
        for s in _build(case)["series"]:
            assert s["color_key"] == ps.color_key(s["point_uuid"])


def test_never_binds_across_sites_and_rejects_mixed_sites():
    a = ps.build_preset_spec(MODEL, "ahu_mats", [_equip("site-a/AHU-1")], CASES["window"])
    b = ps.build_preset_spec(MODEL, "ahu_mats", [_equip("site-b/AHU-1")], CASES["window"])
    assert len(a["series"]) == len(b["series"]) == 1
    assert a["series"][0]["point_uuid"] != b["series"][0]["point_uuid"]
    with pytest.raises(ValueError, match="one site"):
        ps.build_preset_spec(MODEL, "ahu_mats", [_equip("site-a/AHU-1"), _equip("site-b/AHU-1")], CASES["window"])


def test_site_tz_sources_and_window_forms():
    model = json.loads(json.dumps(MODEL))
    for s in model["sites"]:
        s["attrs"].pop("tz", None)
    eq = _equip("site-a/AHU-1")
    w = {"from": 1762041600000, "to": "2026-11-09T00:00:00.500+00:00"}
    assert ps.build_rule_spec(model, "FC1", eq, w)["site"]["tz_source"] == "fallback"
    spec = ps.build_rule_spec(model, "FC1", eq, w, tz="America/Chicago")
    assert spec["site"] == {"ref": "site-a", "tz": "America/Chicago", "tz_source": "option"}
    assert spec["window"] == {"from": "2025-11-02T00:00:00Z", "to": "2026-11-09T00:00:00.500Z"}
    assert ps.build_rule_spec(MODEL, "FC1", eq, w)["site"]["tz_source"] == "model"


def test_rule_not_applicable_to_equip_kind_is_empty():
    spec = ps.build_rule_spec(MODEL, "CHW-1", _equip("site-a/AHU-1"), CASES["window"])
    assert spec["series"] == [] and "does not apply" in spec["selection_reason"]


def test_registry_is_consistent():
    reg = _json(DATA / "rcx_presets.json")["presets"]
    assert len(reg) == 42
    assert len({p["id"] for p in reg}) == len(reg)
    rules = {r["id"] for r in CATALOG["rules"]}
    for p in reg:
        assert set(p) >= {"id", "title", "group", "scope", "equip_kinds", "series", "fault_rules", "min_equips", "default_hours", "aliases"}
        for s in p["series"]:
            assert ("role" in s) != ("markers" in s)
            if "role" in s:
                assert s["role"] in CATALOG["roles"], (p["id"], s["role"])
        assert set(p["fault_rules"]) <= rules
        assert set(p["equip_kinds"]) <= set(CATALOG["equipment_kinds"])
    aliases = {a: p["id"] for p in reg for a in p["aliases"]}
    assert aliases["ahu_cooling_valves"] == "ahu-cooling-valves"
    assert aliases["ahu_heating_valves"] == "ahu-heating-valves"
    assert aliases["ahu_motor_weekly"] == "weekly-fan"
    assert aliases["boiler_motor_weekly"] == "weekly-pump"
    assert aliases["chiller_motor_weekly"] == "weekly-chiller"
    assert aliases["mech_cooling_oat_bins"] == "mech-cooling-chiller-status"
    assert not set(aliases) & {p["id"] for p in reg}
    with pytest.raises(ValueError):
        ps.resolve_preset_id("no-such-preset")


def test_palette_matches_theme_js():
    pal = _json(DATA / "palette.json")
    theme = (ROOT / "nf-app" / "static" / "theme.js").read_text(encoding="utf-8")
    for name in ("light", "dark"):
        for colour in pal["series"][name]:
            assert colour in theme, colour
    assert len(pal["series"]["light"]) == 12 and len(pal["series"]["dark"]) == 8
    assert set(pal["status"]) == {"fault", "ok", "unknown", "stale"}


def test_units_json_matches_the_python_units_table():
    from open_fdd.nf import units as nf_units

    doc = _json(DATA / "units.json")
    samples = [-40.0, 0.0, 20.0, 100.5]
    for row in doc["aliases"]:
        if not row["units_js"]:
            continue
        for name in row["names"]:
            want = nf_units.to_si(1.0, name)
            if want is None:      # spelling only units.js knows (the pandas table is narrower); not ours to widen here
                continue
            for v in samples:
                got = v * row["to_si"]["mul"] + row["to_si"]["add"]
                assert got == pytest.approx(nf_units.to_si(v, name).value, rel=1e-9, abs=1e-9), name
