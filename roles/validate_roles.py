#!/usr/bin/env python3
"""Validate roles/openfdd-roles.json.

    python3 roles/validate_roles.py                      # structure, derivation, units, Haystack binding, NF classes
    python3 roles/validate_roles.py --ontology-dir DIR   # also check every term against the pinned 223P, QUDT and Haystack files

The default run needs only the standard library (jsonschema is used when installed). --ontology-dir needs rdflib and the
files named in the roles file's `sources` (same names as open_fdd/ontology_audit/data/sources.json); sha256 is checked.
Exit status 1 lists every problem.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROLES = HERE / "openfdd-roles.json"
DEFAULT_SCHEMA = HERE / "openfdd-roles.schema.json"
DEFAULT_NF_CLASSES = HERE.parent / "nf-app" / "rules" / "nf_classes.json"

SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
FUNCTION = ("sensor", "sp", "cmd")
CONFIG_ASPECTS = {"s223:Aspect-Setpoint", "s223:Aspect-Maximum", "s223:Aspect-Minimum"}
QUANTIFIABLE = {"s223:QuantifiableObservableProperty", "s223:QuantifiableActuatableProperty"}
ACTUATABLE = {"s223:QuantifiableActuatableProperty", "s223:EnumeratedActuatableProperty"}


def derive(basis: dict, doc: dict) -> str:
    """The role name the derivation rule gives for one s223 basis."""
    lex, d = doc["lexicon"], doc["derivation"]
    order = {a: i for i, a in enumerate(d["aspect_order"])}
    terms: list[str] = []
    for slot in d["slots"]:
        value = basis.get(slot)
        if slot == "connection_point" and basis.get("roles"):
            continue
        if slot == "aspects":
            terms += sorted(value or [], key=lambda a: order.get(a, len(order)))
        elif isinstance(value, list):
            terms += value
        elif value:
            terms.append(value)
    tokens = [lex[t]["token"] for t in terms]
    cls = basis["property_class"]
    suffix = d["suffix"][cls]
    if cls == "s223:QuantifiableActuatableProperty" and CONFIG_ASPECTS & set(basis.get("aspects", [])):
        suffix = ""
    tokens.append(suffix)
    kept: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        if kept and set(tok.split("_")) <= set(kept[-1].split("_")):
            continue
        kept.append(tok)
    return "_".join(kept)


def basis_terms(basis: dict) -> list[str]:
    out = []
    for key, value in basis.items():
        if key in ("property_class", "applies_to"):
            continue
        out += value if isinstance(value, list) else [value]
    return out


def check_schema(doc: dict, schema_path: Path, errs: list[str]) -> None:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return
    if not schema_path.is_file():
        errs.append(f"schema: {schema_path} is missing")
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    checker = jsonschema.FormatChecker()
    if "uri" not in checker.checkers:
        errs.append("schema: uri format checker is not installed (pip install 'jsonschema[format-nongpl]')")
        return
    validator = jsonschema.Draft202012Validator(schema, format_checker=checker)
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        errs.append(f"schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}")


def parent_constraints_overlap(ha: dict, hb: dict) -> bool:
    """True when some parent equipment can satisfy both roles' equip_markers and equip_forbid."""
    req_a, ban_a = set(ha.get("equip_markers") or []), set(ha.get("equip_forbid") or [])
    req_b, ban_b = set(hb.get("equip_markers") or []), set(hb.get("equip_forbid") or [])
    if req_a & ban_a or req_b & ban_b:
        return False
    return not (req_a & ban_b or req_b & ban_a)


def check(doc: dict, nf_classes: set[str] | None = None) -> list[str]:
    errs: list[str] = []
    lex, units, hs_top = doc["lexicon"], doc["units"], doc["haystack"]
    broader = doc["quantity_kind_broader"]
    custom_top = set(hs_top["custom_markers"])
    h4 = set(hs_top["markers"])
    if h4 & custom_top:
        errs.append(f"haystack: markers listed as both Haystack 4 and custom: {sorted(h4 & custom_top)}")

    for term, entry in lex.items():
        ext = term.startswith("ext:")
        if ext != bool(entry.get("extension")):
            errs.append(f"lexicon {term}: extension flag must be set exactly for ext: terms")
        if ext and not (entry.get("closest") and entry.get("why")):
            errs.append(f"lexicon {term}: an extension needs closest and why")
        if entry["token"] == "" and not entry.get("why"):
            errs.append(f"lexicon {term}: an empty token needs why")
        if entry["token"] and not SNAKE.match(entry["token"]):
            errs.append(f"lexicon {term}: token {entry['token']!r} is not snake_case")
    tokens = [e["token"] for e in lex.values() if e["token"]]
    for tok in {t for t in tokens if tokens.count(t) > 1}:
        errs.append(f"lexicon: token {tok!r} is used by more than one term")

    names: dict[str, dict] = {}
    seen_alias: dict[str, str] = {}
    for r in doc["roles"]:
        name, b, hs = r["role"], r["s223"], r["haystack"]
        where = f"role {name}"
        if name in names:
            errs.append(f"{where}: duplicate role")
        names[name] = r
        if not SNAKE.match(name):
            errs.append(f"{where}: not snake_case")
        missing = [t for t in basis_terms(b) if t not in lex]
        if missing:
            errs.append(f"{where}: basis terms not in lexicon: {missing}")
            continue
        want = derive(b, doc)
        if want != name:
            errs.append(f"{where}: derivation gives {want!r}")
        is_ext = any(t.startswith("ext:") for t in basis_terms(b))
        if r["grounding"] != ("extension" if is_ext else "s223"):
            errs.append(f"{where}: grounding must be {'extension' if is_ext else 's223'}")

        cls = b["property_class"]
        unit = r["unit"]
        if cls in QUANTIFIABLE:
            if not b.get("quantity_kind") or not unit or r["value_type"] != "number":
                errs.append(f"{where}: a quantifiable property needs quantity_kind, unit and value_type number")
            elif unit not in units:
                errs.append(f"{where}: unit {unit} is not in units")
            else:
                qk = b["quantity_kind"].split(":", 1)[1]
                if not ({qk} | set(broader.get(qk, []))) & set(units[unit]["quantity_kinds"]):
                    errs.append(f"{where}: {unit} does not apply to quantitykind:{qk}")
                if qk == "DimensionlessRatio" and not b.get("constituent") and unit != doc["ratio_unit"]:
                    errs.append(f"{where}: ratios use {doc['ratio_unit']}")
                if r["range"] != units[unit]["range"]:
                    errs.append(f"{where}: range must be the unit's range {units[unit]['range']}")
        else:
            if unit is not None or not b.get("enumeration_kind"):
                errs.append(f"{where}: an enumerated property has an enumeration_kind and no unit")
            if r["value_type"] not in ("boolean", "enumeration"):
                errs.append(f"{where}: an enumerated property is boolean or enumeration")

        if r["writable"] == "model":
            if cls not in ACTUATABLE:
                errs.append(f"{where}: only an actuatable property may be writable")
            if r["derived"]:
                errs.append(f"{where}: a derived role is never writable")
            if {"s223:Aspect-Maximum", "s223:Aspect-Minimum"} & set(b.get("aspects", [])):
                errs.append(f"{where}: limits are never writable")
        for app, use in r["consumers"].items():
            if use in ("write", "readwrite") and r["writable"] != "model":
                errs.append(f"{where}: {app} writes it but writable is {r['writable']}")
        if r["derived"] and cls in ACTUATABLE:
            errs.append(f"{where}: a derived role is observable")

        # Haystack binding
        markers, forbid = set(hs["markers"]), set(hs["forbid"])
        custom = set(hs.get("custom_markers", []))
        alts = [set(a) for a in hs.get("alt_markers", [])]
        equip_markers, equip_forbid = set(hs.get("equip_markers", [])), set(hs.get("equip_forbid", []))
        used = markers | set(hs.get("optional", [])) | equip_markers | equip_forbid | set().union(set(), *alts)
        if equip_markers & equip_forbid:
            errs.append(f"{where}: equip_markers overlap equip_forbid: {sorted(equip_markers & equip_forbid)}")
        kind_for = {"number": "Number", "boolean": "Bool", "enumeration": "Str"}
        if hs["kind"] != kind_for[r["value_type"]]:
            errs.append(f"{where}: haystack.kind {hs['kind']!r} does not match value_type {r['value_type']}")
        for m in sorted(used - h4):
            errs.append(f"{where}: marker {m!r} is not in haystack.markers")
        for m in sorted(forbid - h4 - custom_top):
            errs.append(f"{where}: forbidden marker {m!r} is neither Haystack 4 nor a declared custom marker")
        for m in sorted(custom - custom_top):
            errs.append(f"{where}: custom marker {m!r} is not declared in haystack.custom_markers")
        if (hs["conformance"] == "custom") != bool(custom):
            errs.append(f"{where}: conformance is custom exactly when custom_markers are required")
        if (markers | custom) & forbid:
            errs.append(f"{where}: forbid overlaps markers: {sorted((markers | custom) & forbid)}")
        if hs["binding_scope"] == "derived":
            if not r["derived"]:
                errs.append(f"{where}: binding_scope derived needs derived true")
        else:
            expect = ("sp" if CONFIG_ASPECTS & set(b.get("aspects", [])) else
                      "cmd" if cls in ACTUATABLE else "sensor")
            for tagset in [markers] + alts:
                fn = tagset & set(FUNCTION)
                if fn == {expect} or (not fn and set(FUNCTION) - {expect} <= forbid):
                    continue
                errs.append(f"{where}: Haystack set {sorted(tagset)} needs exactly the function marker {expect!r}, "
                            f"or none and forbid the other two")
            for alt in alts:
                if alt <= markers or markers <= alt:
                    errs.append(f"{where}: alt set {sorted(alt)} is redundant with markers {sorted(markers)}")
        if "sp" in markers and not ({"s223:Aspect-Maximum", "s223:Aspect-Minimum"} & set(b.get("aspects", []))):
            if not {"max", "min"} <= forbid:
                errs.append(f"{where}: a setpoint must forbid max and min")
        if "s223:Aspect-Maximum" in b.get("aspects", []) and ("max" not in markers or "min" not in forbid):
            errs.append(f"{where}: a maximum needs marker max and forbids min")
        if "s223:Aspect-Minimum" in b.get("aspects", []) and ("min" not in markers or "max" not in forbid):
            errs.append(f"{where}: a minimum needs marker min and forbids max")
        if unit in units and hs["unit"] != units[unit]["haystack"]:
            errs.append(f"{where}: haystack.unit must be {units[unit]['haystack']!r}")
        if nf_classes is not None:
            for c in hs["classes"]:
                if c not in nf_classes:
                    errs.append(f"{where}: NF class {c!r} is not in nf_classes.json")

        for alias in r["aliases"] + r["legacy_keys"]:
            if alias in seen_alias and seen_alias[alias] != name:
                errs.append(f"{where}: alias {alias!r} also maps to {seen_alias[alias]}")
            seen_alias[alias] = name

    for alias, owner in seen_alias.items():
        if alias in names and alias != owner:
            errs.append(f"alias {alias!r} of {owner} is itself a role name")
    for amb in doc.get("ambiguous_legacy_names", {}):
        if amb in seen_alias and amb not in names:
            errs.append(f"ambiguous name {amb!r} must not be an alias of one role")
    for r in doc["roles"]:
        for fb in r.get("accepts_fallback", []):
            if fb not in names:
                errs.append(f"role {r['role']}: fallback {fb!r} is not a role")
    for conv in doc["ingest_conversions"]:
        if conv["to"] not in units:
            errs.append(f"ingest {conv['from']!r}: target {conv['to']} is not in units")

    # Binding safety between roles.
    roles = [r for r in doc["roles"] if r["haystack"]["binding_scope"] != "derived"]
    for a in roles:
        ha = a["haystack"]
        for c in ha["classes"]:
            for b in roles:
                if b is a or a["role"] > b["role"]:
                    continue
                hb = b["haystack"]
                if c in hb["classes"] and ha["binding_scope"] == hb["binding_scope"] \
                        and parent_constraints_overlap(ha, hb):
                    errs.append(f"role {a['role']}: class {c!r} also binds {b['role']} "
                                f"where the parent constraints overlap")
        sa = set(ha["markers"]) | set(ha.get("custom_markers", []))
        for b in roles:
            if b is a:
                continue
            hb = b["haystack"]
            sb = set(hb["markers"]) | set(hb.get("custom_markers", []))
            same_scope = ha["binding_scope"] == hb["binding_scope"] and parent_constraints_overlap(ha, hb)
            if sa == sb and same_scope and a["role"] < b["role"]:
                errs.append(f"roles {a['role']} and {b['role']}: identical markers in the same scope")
            if a["writable"] == "model" and sa < sb and same_scope and not ((sb - sa) & set(ha["forbid"])):
                errs.append(f"role {a['role']}: writable, and a {b['role']} point also matches it; forbid one of {sorted(sb - sa)}")
    return errs


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


REQUIRED_SOURCES = ("s223", "haystack", "haystack-units", "qudt-units", "qudt-quantitykinds")


def check_ontologies(doc: dict, ontology_dir: Path) -> list[str]:
    """Every s223, QUDT and Haystack term exists in the pinned files; units carry the quantity kinds claimed."""
    errs: list[str] = []
    names = [s.get("name") for s in doc.get("sources", [])]
    for name in REQUIRED_SOURCES:
        count = names.count(name)
        if count != 1:
            errs.append(f"ontology: sources must contain exactly one {name!r} entry (found {count})")
    if errs:
        return errs

    import rdflib  # type: ignore

    files = {s["name"]: ontology_dir / s["file"] for s in doc["sources"]}
    for s in doc["sources"]:
        p = files[s["name"]]
        if not p.exists():
            errs.append(f"ontology: {p} is missing")
        elif s.get("sha256") and sha256(p) != s["sha256"]:
            errs.append(f"ontology: {p.name} sha256 differs from the pin")
    if errs:
        return errs
    s223 = rdflib.Graph().parse(files["s223"])
    qunit = rdflib.Graph().parse(files["qudt-units"])
    qk = rdflib.Graph().parse(files["qudt-quantitykinds"])
    hs = rdflib.Graph().parse(files["haystack"])
    ns = {"s223": "http://data.ashrae.org/standard223#", "g36": "http://data.ashrae.org/standard223/1.0/extensions/g36#",
          "quantitykind": "http://qudt.org/vocab/quantitykind/", "unit": "http://qudt.org/vocab/unit/"}
    hs_ns = "https://project-haystack.org/def/"
    qudt = rdflib.Namespace("http://qudt.org/schema/qudt/")
    skos = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")

    def iri(term: str) -> rdflib.URIRef:
        p, local = term.split(":", 1)
        return rdflib.URIRef(ns[p] + local)

    terms = set(doc["lexicon"]) | {r["s223"]["property_class"] for r in doc["roles"]} | \
        {t for r in doc["roles"] for t in r["s223"].get("applies_to", [])}
    for t in sorted(terms):
        if t.startswith("ext:"):
            continue
        g = qk if t.startswith("quantitykind:") else s223
        if (iri(t), None, None) not in g:
            errs.append(f"ontology: {t} is not defined in the pinned {'QUDT' if g is qk else '223P'} snapshot")
    for t in sorted(doc["quantity_kind_broader"]):
        chain, node = [], iri("quantitykind:" + t)
        while (b := qk.value(node, skos.broader)) is not None:
            chain.append(str(b).rsplit("/", 1)[1])
            node = b
        if chain != doc["quantity_kind_broader"][t]:
            errs.append(f"ontology: quantitykind:{t} broader chain is {chain}")
    for u, spec in doc["units"].items():
        have = {str(o).rsplit("/", 1)[1] for o in qunit.objects(iri(u), qudt.hasQuantityKind)}
        if not have:
            errs.append(f"ontology: {u} is not defined in the pinned QUDT snapshot")
        elif not set(spec["quantity_kinds"]) <= have:
            errs.append(f"ontology: {u} lacks quantity kinds {sorted(set(spec['quantity_kinds']) - have)}")
    hs_defs = {str(s).rsplit("#", 1)[1] for s in hs.subjects() if str(s).startswith(hs_ns) and "#" in str(s)}
    for m in doc["haystack"]["markers"]:
        if m not in hs_defs:
            errs.append(f"ontology: Haystack marker {m!r} is not in the pinned defs")
    for m in doc["haystack"]["custom_markers"]:
        if m in hs_defs:
            errs.append(f"ontology: {m!r} is a Haystack 4 def; it is not custom")
    if "haystack-units" in files:
        symbols = set()
        for line in files["haystack-units"].read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("--"):
                symbols.update(line.split(",")[1:])
        for u, spec in doc["units"].items():
            if spec["haystack"] and spec["haystack"] not in symbols:
                errs.append(f"ontology: Haystack unit {spec['haystack']!r} is not in units.txt")
        for c in doc["ingest_conversions"]:
            if c["from"] != "fraction" and c["from"] not in symbols:
                errs.append(f"ontology: ingest unit {c['from']!r} is not in units.txt")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roles", nargs="?", type=Path, default=DEFAULT_ROLES)
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    ap.add_argument("--nf-classes", type=Path, default=None,
                    help="NF class catalog (default: nf-app/rules/nf_classes.json when that file exists)")
    ap.add_argument("--ontology-dir", type=Path)
    args = ap.parse_args(argv)
    doc = json.loads(args.roles.read_text(encoding="utf-8"))
    errs: list[str] = []
    check_schema(doc, args.schema, errs)
    if any(e.startswith("schema:") for e in errs):
        for e in errs:
            print(e, file=sys.stderr)
        print(f"FAIL: {args.roles.name} schema, {len(errs)} problems")
        return 1
    nf_path = args.nf_classes if args.nf_classes is not None else DEFAULT_NF_CLASSES
    nf = None
    if nf_path.exists():
        raw = json.loads(nf_path.read_text(encoding="utf-8"))
        items = raw["classes"] if isinstance(raw, dict) else raw
        nf = {c["name"] if isinstance(c, dict) else c for c in items}
    elif args.nf_classes is not None:
        errs.append(f"nf classes: {nf_path} is missing")
    errs += check(doc, nf)
    if args.ontology_dir:
        errs += check_ontologies(doc, args.ontology_dir)
    for e in errs:
        print(e, file=sys.stderr)
    ext = sum(r["grounding"] == "extension" for r in doc["roles"])
    status = "FAIL" if errs else "ok"
    print(f"{status}: {args.roles.name} {doc['version']}, {len(doc['roles'])} roles "
          f"({len(doc['roles']) - ext} s223, {ext} extension), {len(errs)} problems")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
