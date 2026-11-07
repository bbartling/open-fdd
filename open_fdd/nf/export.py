"""Readers for the NF app's offline exports: the Export-tab CSV and the Model & RDF Turtle.

CSV (``nf-app/static/export.js``): UTF-8 with a BOM (so Excel reads degree signs), CRLF line ends,
header ``timestamp`` (local wall clock, no zone), ``timestamp_utc`` (ISO, Z), then one column per
point named ``"<equip> <point dis> [<unit>]"`` (equip and unit parts dropped when empty; a repeated
name gets `` (2)``, `` (3)``...). Cells are numbers; a text cell Excel could read as a formula
starts with ``'``. The unit in brackets is whatever the Export tab was set to (stored or display
system), so values are converted to SI from that unit.

Turtle: ``modelToTurtle`` in ``nf-app/static/model.js``. Needs the optional ``rdflib`` extra.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Mapping

from open_fdd.nf.client import NFError
from open_fdd.nf.model import (FRACTION_UNIT, Model, Point, column_for, load_catalog, role_scales, si_plan_for)

BOM = "﻿"
_UNIT = re.compile(r"\s*\[([^\]]*)\]\s*$")
_DUP = re.compile(r"\s\(\d+\)$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def parse_column(label: str) -> tuple[str, str]:
    """``"AHU-1 Discharge Air Temp [°F]"`` -> (``"AHU-1 Discharge Air Temp"``, ``"°F"``)."""
    label = _DUP.sub("", label.strip())
    m = _UNIT.search(label)
    return (label[:m.start()].strip(), m.group(1).strip()) if m else (label, "")


def read_csv_export(path: str | Path | io.TextIOBase):
    """The app's CSV as a DataFrame with a UTC DatetimeIndex and the original column labels.

    ``df.attrs["columns"]`` = ``{label: {"name": ..., "unit": ...}}`` (name without the unit part).
    """
    import pandas as pd

    if hasattr(path, "read"):
        text = path.read()
    else:
        text = Path(path).read_text(encoding="utf-8-sig")
    text = text.lstrip(BOM)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "timestamp_utc" not in rows[0]:
        raise NFError("not an Open-FDD CSV export (no timestamp_utc column)")
    header = [h.strip() for h in rows[0]]
    ts_i = header.index("timestamp_utc")
    labels = [h for i, h in enumerate(header) if i > ts_i]
    data: dict[str, list[float]] = {h: [] for h in labels}
    index: list[str] = []
    for row in rows[1:]:
        if not row or not row[ts_i].strip():
            continue
        index.append(row[ts_i].strip())
        for h, cell in zip(labels, row[ts_i + 1:] + [""] * (len(labels) - len(row[ts_i + 1:]))):
            try:
                data[h].append(float(cell))
            except ValueError:
                data[h].append(float("nan"))
    df = pd.DataFrame(data, index=pd.DatetimeIndex(pd.to_datetime(index, utc=True), name="timestamp_utc"))
    df.attrs["columns"] = {h: dict(zip(("name", "unit"), parse_column(h))) for h in labels}
    return df


def csv_frames(
    path: str | Path | io.TextIOBase,
    column_roles: Mapping[str, str] | None = None,
    site: str = "csv",
) -> dict[tuple[str, str], Any]:
    """Equipment frames (SI, Haystack role columns) from an Export-tab CSV, for ``run_rules``.

    A CSV has no model, so a column is matched to a role by its point name: the text after the
    equipment name equals (or ends with) a catalog role name or key (``discharge-air-temp``,
    ``ahu_sat`` ...), or you pass ``column_roles={"AHU-1 SAT [°F]": "ahu_sat"}`` (SQL role keys or
    pandas column names). The equipment is the label's prefix before that name. A unitless column
    whose values all lie in 0-1 is kept as a fraction/boolean role (it is the same in both).
    Everything else is dropped; the frame's ``attrs["skipped"]`` says why.
    """
    import pandas as pd

    df = read_csv_export(path)
    cat = load_catalog()
    by_name: dict[str, str] = {}
    for key, d in cat["roles"].items():
        for alias in (key, d.get("name", ""), column_for(key)):
            if alias:
                by_name.setdefault(_norm(alias), key)
    explicit = {_norm(k): v for k, v in (column_roles or {}).items()}
    names = sorted(by_name, key=len, reverse=True)
    groups: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for label, meta in df.attrs["columns"].items():
        name, unit = meta["name"], meta["unit"]
        role, equip = explicit.get(_norm(label)), ""
        if role:
            role = by_name.get(_norm(role), role)
            equip = name
            for alias in (role, cat["roles"].get(role, {}).get("name", ""), column_for(role)):
                if alias and _norm(name).endswith(_norm(alias)):
                    equip = name[: max(len(name) - len(alias), 0)].strip()
                    break
        else:
            tail = next((n for n in names if _norm(name).endswith(n) and len(_norm(name)) >= len(n)), None)
            if tail:
                role = by_name[tail]
                words = name.split()
                equip = ""
                for cut in range(len(words) + 1):
                    if _norm(" ".join(words[cut:])) == tail:
                        equip = " ".join(words[:cut]).strip()
                        break
        if role not in cat["roles"]:
            skipped[label] = "no role matched this point name (pass column_roles)"
            continue
        series = df[label]
        kind = "Number"
        if unit.lower() in ("bool", "boolean"):  # what `open-fdd-nf pull` writes for 0/1 roles
            kind, unit = "Bool", ""
        elif not unit and series.dropna().between(0, 1).all() and series.notna().any():
            kind = "Bool"  # unitless 0-1: valid as a fraction or a 0/1 status either way
        plan = si_plan_for(role, Point("", name, name, [], unit, kind, equip, "", "", "", "", None))
        if plan.convert is None:
            skipped[label] = f"role {role} {plan.reason}"
            continue
        g = groups.setdefault(equip or "equip", {"cols": {}, "units": {}, "bind": {}})
        col = column_for(role)
        if col in g["cols"]:
            continue
        g["cols"][col] = plan.convert(series.astype("float64"))
        g["units"][col] = plan.unit
        g["bind"][col] = {"role": role, "name": label, "unit": plan.unit, "source_unit": unit}
    out: dict[tuple[str, str], Any] = {}
    for equip, g in groups.items():
        f = pd.DataFrame(g["cols"]).sort_index()
        f.index.name = "timestamp_utc"
        idx = f.index
        step = float(idx.to_series().diff().dt.total_seconds().median()) if len(idx) > 1 else 300.0
        f.attrs.update({"equipment_id": equip, "site_id": site, "equipment_type": "",
                        "role_units": g["units"], "bindings": g["bind"], "skipped": skipped,
                        "window_sec": int(step) if step == step and step > 0 else 300})
        out[(site, equip)] = f
    return out


# ---------------------------------------------------------------------------- Turtle
def read_turtle(source: str | Path) -> Model:
    """A ``Model`` (sites, equips, devices, points) from the app's Turtle export (needs ``rdflib``).

    Ids are the Turtle local names (what the refs point at); a point's uuid is its
    ``ref:hasTimeseriesId``.
    """
    try:
        from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
    except ImportError as exc:  # pragma: no cover - optional extra
        raise NFError("reading Turtle needs rdflib: pip install 'open-fdd[rdf]'") from exc
    g = Graph()
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).is_file()):
        g.parse(str(source), format="turtle")
    else:
        g.parse(data=str(source), format="turtle")
    REF = Namespace("https://brickschema.org/schema/Brick/ref#")
    PH = Namespace("https://project-haystack.org/def/ph/")
    local = next((str(ns) for p, ns in g.namespaces() if p == "local"), "")

    def lname(node: Any) -> str:
        s = str(node)
        return s[len(local):] if local and s.startswith(local) else re.split(r"[#/]", s)[-1]

    def one(s: Any, suffix: str) -> str:
        for p, o in g.predicate_objects(s):
            if str(p).endswith(suffix):
                return str(o) if isinstance(o, Literal) else lname(o)
        return ""

    kinds = {"site": [], "equip": [], "device": [], "point": []}
    for s, _, t in g.triples((None, RDF.type, None)):
        k = re.split(r"[#/]", str(t))[-1]
        if k in kinds and isinstance(s, URIRef):
            kinds[k].append(s)

    def tags(s: Any) -> list[str]:
        return sorted(lname(o) for o in g.objects(s, PH.hasTag))

    def entity(s: Any, extra: dict[str, str] | None = None) -> dict:
        attrs = {"id": lname(s), "dis": str(g.value(s, RDFS.label) or lname(s)),
                 "markers": ",".join(tags(s))}
        for k, suffix in (("siteRef", "siteRef"), ("equipRef", "equipRef"), ("deviceRef", "deviceRef")):
            v = one(s, suffix)
            if v:
                attrs[k] = v
        attrs.update(extra or {})
        return {"uuid": lname(s), "name": attrs["dis"], "attrs": attrs}

    sites = [{**entity(s), "pointType": "SITE"} for s in sorted(kinds["site"])]
    equips = [{**entity(s), "pointType": "EQUIPMENT"} for s in sorted(kinds["equip"])]
    devices = [{**entity(s), "pointType": "DEVICE"} for s in sorted(kinds["device"])]
    points: list[Point] = []
    for s in sorted(kinds["point"]):
        uuid = lname(s)
        for ref in g.objects(s, REF.hasExternalReference):
            tid = g.value(ref, REF.hasTimeseriesId)
            if tid is not None:
                uuid = str(tid)
                break
        extra = {"unit": one(s, "unit"), "kind": one(s, "kind"), "class": one(s, "nfClass"),
                 "weatherStationRef": one(s, "weatherStationRef")}
        rec = {**entity(s, {k: v for k, v in extra.items() if v}), "uuid": uuid, "pointType": "POINT"}
        a = rec["attrs"]
        points.append(Point(uuid=uuid, name=" ".join(t for t in tags(s) if t not in {"point", "his", "cur", "writable", "sensor"}) or a["dis"],
                            dis=a["dis"], tags=tags(s), unit=a.get("unit", ""), kind=a.get("kind") or "Number",
                            equip_ref=a.get("equipRef", ""), site_ref=a.get("siteRef", ""),
                            weather_ref=a.get("weatherStationRef", ""), device_ref=a.get("deviceRef", ""),
                            cls=a.get("class", ""), latest=None, rec=rec))
    if not sites:
        raise NFError("no phIoT:site in this Turtle")
    return Model(sites, equips, devices, points)
