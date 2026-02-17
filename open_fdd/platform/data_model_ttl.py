"""
Generate Brick TTL from current DB state (sites, equipment, points).

Single source of truth = DB. TTL is derived for FDD column_map and SPARQL validation.
Points use rdfs:label = external_id (time-series reference) and optional ofdd:mapsToRuleInput = fdd_input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn

BRICK = "https://brickschema.org/schema/Brick#"
OFDD = "http://openfdd.local/ontology#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
BASE = "http://openfdd.local/site#"


def _escape(s: str) -> str:
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _append_point(lines: list[str], p: dict[str, Any], parent_uri: str) -> None:
    pid = str(p["id"]).replace("-", "_")
    pt_uri = f":pt_{pid}"
    brick_type = p.get("brick_type") or "Point"
    label = _escape(p["external_id"])
    lines.append(f"{pt_uri} a brick:{brick_type} ;")
    lines.append(f'    rdfs:label "{label}" ;')
    if p.get("fdd_input"):
        lines.append(f"    brick:isPointOf {parent_uri} ;")
        lines.append(f'    ofdd:mapsToRuleInput "{_escape(p["fdd_input"])}" .')
    else:
        lines.append(f"    brick:isPointOf {parent_uri} .")
    lines.append("")


def _prefixes() -> str:
    return """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix : <http://openfdd.local/site#> .

"""


def build_ttl_from_db(site_id: UUID | None = None) -> str:
    """
    Build TTL: sites, equipment (with type), points (brick_type, label=external_id, mapsToRuleInput=fdd_input).
    Points without equipment get a synthetic equipment per site.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if site_id:
                cur.execute("SELECT id, name FROM sites WHERE id = %s", (str(site_id),))
            else:
                cur.execute("SELECT id, name FROM sites ORDER BY name")
            sites = cur.fetchall()
            if not sites:
                return _prefixes()

            site_ids = [str(s["id"]) for s in sites]
            cur.execute(
                """SELECT id, site_id, name, equipment_type FROM equipment
                   WHERE site_id = ANY(%s::uuid[]) ORDER BY site_id, name""",
                (site_ids,),
            )
            equipment = cur.fetchall()
            cur.execute(
                """SELECT id, site_id, external_id, brick_type, fdd_input, unit, equipment_id
                   FROM points WHERE site_id = ANY(%s::uuid[]) ORDER BY site_id, external_id""",
                (site_ids,),
            )
            points_rows = cur.fetchall()

    lines = [_prefixes()]
    eq_by_site: dict[str, list[dict]] = {}
    for e in equipment:
        sid = str(e["site_id"])
        eq_by_site.setdefault(sid, []).append(e)
    pts_by_eq: dict[str, list[dict]] = {}
    pts_orphan: dict[str, list[dict]] = {}
    for p in points_rows:
        sid = str(p["site_id"])
        eid = p.get("equipment_id")
        if eid:
            pts_by_eq.setdefault(str(eid), []).append(p)
        else:
            pts_orphan.setdefault(sid, []).append(p)

    for site in sites:
        sid = str(site["id"])
        sname = _escape(site["name"])
        sref = f":site_{sid.replace('-', '_')}"
        lines.append(f"{sref} a brick:Site ;")
        lines.append(f'    rdfs:label "{sname}" .')
        lines.append("")

        for e in eq_by_site.get(sid, []):
            eid = str(e["id"])
            eref = f":eq_{eid.replace('-', '_')}"
            ename = _escape(e["name"])
            etype = (e.get("equipment_type") or "Equipment").replace(" ", "_")
            lines.append(f"{eref} a brick:{etype} ;")
            lines.append(f'    rdfs:label "{ename}" ;')
            lines.append(f"    brick:isPartOf {sref} ;")
            lines.append(f'    ofdd:equipmentType "{etype}" .')
            lines.append("")
            for p in pts_by_eq.get(eid, []):
                _append_point(lines, p, eref)
            lines.append("")

        orphans = pts_orphan.get(sid, [])
        if orphans:
            oref = f":site_{sid.replace('-', '_')}_points"
            lines.append(f"{oref} a brick:Equipment ;")
            lines.append('    rdfs:label "Points" ;')
            lines.append(f"    brick:isPartOf {sref} ;")
            lines.append('    ofdd:equipmentType "Unknown" .')
            lines.append("")
            for p in orphans:
                _append_point(lines, p, oref)
            lines.append("")

    return "\n".join(lines)


def sync_ttl_to_file(site_id: UUID | None = None) -> None:
    """
    Write current DB state as Brick TTL to config file. Called automatically on any
    CRUD that affects sites/equipment/points. Path from OFDD_BRICK_TTL_PATH (default: config/brick_model.ttl).
    Falls back to /tmp/brick_model.ttl if config path is not writable (e.g. Docker read-only).
    """
    ttl = build_ttl_from_db(site_id=site_id)
    path_str = getattr(
        get_platform_settings(), "brick_ttl_path", "config/brick_model.ttl"
    )
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(ttl, encoding="utf-8")
    except OSError:
        Path("/tmp/brick_model.ttl").write_text(ttl, encoding="utf-8")


def get_bacnet_scan_ttl_path() -> Path:
    """Path where BACnet discovery-to-rdf TTL is stored."""
    path_str = getattr(
        get_platform_settings(), "bacnet_scan_ttl_path", "config/bacnet_scan.ttl"
    )
    p = Path(path_str)
    return (Path.cwd() / p) if not p.is_absolute() else p


def get_bacnet_scan_ttl() -> str | None:
    """Read current BACnet scan TTL if file exists and has content."""
    path = get_bacnet_scan_ttl_path()
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text if text else None


def store_bacnet_scan_ttl(ttl: str) -> None:
    """
    Store BACnet discovery TTL (from diy-bacnet-server client_discovery_to_rdf).
    Merged into SPARQL graph when get_ttl_for_sparql() is used.
    """
    path = get_bacnet_scan_ttl_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(ttl, encoding="utf-8")
    except OSError:
        Path("/tmp/bacnet_scan.ttl").write_text(ttl, encoding="utf-8")


def _rdf_value_to_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(getattr(v, "value", v))
    except (TypeError, ValueError):
        return 0


def _rdf_value_to_str(v: Any) -> str:
    if v is None:
        return ""
    return str(getattr(v, "value", v)).strip()


def parse_bacnet_ttl_to_discovery(ttl: str) -> tuple[list[dict], list[dict]]:
    """
    Parse BACnet RDF TTL (from discovery-to-rdf) into devices and point_discoveries
    for creating site/equipment/points in the DB. Returns (devices, point_discoveries).
    """
    try:
        from rdflib import Graph

        g = Graph()
        g.parse(data=ttl, format="turtle")
    except Exception:
        return [], []

    BACNET = "http://data.ashrae.org/bacnet/2020#"
    q = """
    PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
    SELECT ?di ?oid ?oname WHERE {
      ?device a bacnet:Device ;
              bacnet:device-instance ?di ;
              bacnet:contains ?obj .
      ?obj bacnet:object-identifier ?oid .
      OPTIONAL { ?obj bacnet:object-name ?oname }
    }
    """
    rows: list[tuple[int, str, str | None]] = []
    for row in g.query(q):
        di = _rdf_value_to_int(row.di)
        oid = _rdf_value_to_str(row.oid)
        oname = _rdf_value_to_str(row.oname) if row.oname else None
        if oid:
            rows.append((di, oid, oname or None))

    # Build devices: one per device_instance; name from device object if present
    device_names: dict[int, str] = {}
    for di, oid, oname in rows:
        if oid.startswith("device,"):
            try:
                inst = int(oid.split(",", 1)[1])
                if inst == di and oname:
                    device_names[di] = oname
            except (ValueError, IndexError):
                pass
    devices = [
        {"device_instance": di, "name": device_names.get(di) or f"BACnet device {di}"}
        for di in sorted({r[0] for r in rows})
    ]

    # point_discoveries: per device, list of {object_identifier, object_name}
    by_device: dict[int, list[dict]] = {}
    for di, oid, oname in rows:
        by_device.setdefault(di, []).append(
            {"object_identifier": oid, "object_name": oname or oid.replace(",", "_")}
        )
    point_discoveries = [
        {"device_instance": di, "objects": objs}
        for di in sorted(by_device.keys())
        for objs in [by_device[di]]
    ]
    return devices, point_discoveries


def get_ttl_for_sparql(site_id: UUID | None = None) -> str:
    """
    TTL used for SPARQL: DB-derived TTL merged with BACnet scan TTL (if present).
    Single graph so queries see both BRICK (sites/equipment/points) and BACnet devices/objects.
    """
    db_ttl = build_ttl_from_db(site_id=site_id)
    bacnet_ttl = get_bacnet_scan_ttl()
    if not bacnet_ttl:
        return db_ttl
    try:
        from rdflib import Graph

        g = Graph()
        g.parse(data=db_ttl, format="turtle")
        g.parse(data=bacnet_ttl, format="turtle")
        out = g.serialize(format="turtle")
        return out.decode("utf-8") if isinstance(out, bytes) else out
    except Exception:
        return db_ttl
