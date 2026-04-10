"""
Generate Brick TTL from current DB state (sites, equipment, points).

Single source of truth = DB. TTL is derived for FDD column_map and SPARQL validation.
Points use rdfs:label = external_id (time-series reference). Brick type is sufficient
for FDD resolution; ofdd:mapsToRuleInput (fdd_input) is optional and only used when
multiple points share the same Brick class (disambiguation).

One unified TTL file (config/data_model.ttl): Brick section first, then BACnet discovery
section after BACNET_SECTION_MARKER. CRUD and point_discovery_to_graph update the in-memory graph; sync writes this file.
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from openfdd_stack.platform.config import get_platform_settings
from openfdd_stack.platform.database import get_conn

BACNET_SECTION_MARKER = "# --- BACnet discovery ---"

# In-memory cache: (path, bacnet_section) so we avoid reading the file on every sync.
_bacnet_cache: tuple[Path, str | None] | None = None
_sync_timer: threading.Timer | None = None
_sync_timer_lock = threading.Lock()

BRICK = "https://brickschema.org/schema/Brick#"
OFDD = "http://openfdd.local/ontology#"
S223 = "http://data.ashrae.org/standard223#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
BASE = "http://openfdd.local/site#"
logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    """Escape for Turtle double-quoted literals (labels, comments, embedded JSON)."""
    if s is None:
        return ""
    return (
        s.replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )


def _timeseries_store_uri() -> str:
    """
    Best-effort canonical storage URI for ref:storedAt.
    Uses OFDD_DB_DSN host/port/db without embedding credentials.
    """
    dsn = getattr(get_platform_settings(), "db_dsn", "") or ""
    try:
        u = urlparse(dsn)
        host = u.hostname or "localhost"
        port = u.port or 5432
        db = (u.path or "/openfdd").lstrip("/") or "openfdd"
        return f"postgresql://{host}:{port}/{db}/timeseries_readings"
    except Exception:
        return "postgresql://localhost:5432/openfdd/timeseries_readings"


def _append_point(lines: list[str], p: dict[str, Any], parent_uri: str) -> None:
    pid = str(p["id"]).replace("-", "_")
    pt_uri = f":pt_{pid}"
    brick_type = p.get("brick_type") or "Point"
    label = _escape(p["external_id"])
    polling = p.get("polling", True)
    lines.append(f"{pt_uri} a brick:{brick_type} ;")
    lines.append(f'    rdfs:label "{label}" ;')
    lines.append(f"    ofdd:polling {'true' if polling else 'false'} ;")
    mc = p.get("modbus_config")
    if isinstance(mc, dict) and mc:
        mc_json = json.dumps(mc, separators=(",", ":"), sort_keys=True)
        lines.append(f'    ofdd:modbusConfig "{_escape(mc_json)}" ;')
    if p.get("unit"):
        lines.append(f'    ofdd:unit "{_escape(p["unit"])}" ;')
    bacnet_id = p.get("bacnet_device_id")
    obj_id = p.get("object_identifier")
    obj_name = p.get("object_name")
    has_bacnet_ref = bool(bacnet_id is not None and str(bacnet_id).strip() and obj_id is not None and str(obj_id).strip())
    ts_id = _escape(p["external_id"])
    stored_at = _escape(_timeseries_store_uri())
    if bacnet_id is not None and str(bacnet_id).strip():
        lines.append(f'    ofdd:bacnetDeviceId "{_escape(str(bacnet_id).strip())}" ;')
    if obj_id is not None and str(obj_id).strip():
        lines.append(f'    ofdd:objectIdentifier "{_escape(str(obj_id).strip())}" ;')
    # Brick v1.4 external representations: Timeseries reference is always present;
    # BACnet reference is present when both device id and object id exist.
    if has_bacnet_ref:
        bdev = _escape(str(bacnet_id).strip())
        boid = _escape(str(obj_id).strip())
        lines.append("    ref:hasExternalReference [")
        lines.append("        a ref:BACnetReference ;")
        lines.append(f'        bacnet:object-identifier "{boid}" ;')
        if obj_name is not None and str(obj_name).strip():
            lines.append(f'        bacnet:object-name "{_escape(str(obj_name).strip())}" ;')
        lines.append(f'        brick:BACnetURI "bacnet://{bdev}/{boid}/present-value" ;')
        lines.append(f"        bacnet:objectOf <bacnet://{bdev}>")
        lines.append("    ] ;")
    lines.append("    ref:hasExternalReference [")
    lines.append("        a ref:TimeseriesReference ;")
    lines.append(f'        ref:hasTimeseriesId "{ts_id}" ;')
    lines.append(f'        ref:storedAt "{stored_at}"')
    lines.append("    ] ;")
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
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
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
                """SELECT id, site_id, name, equipment_type, metadata, feeds_equipment_id, fed_by_equipment_id FROM equipment
                   WHERE site_id = ANY(%s::uuid[]) ORDER BY site_id, name""",
                (site_ids,),
            )
            equipment = cur.fetchall()
            cur.execute(
                """SELECT id, site_id, external_id, brick_type, fdd_input, unit, equipment_id, COALESCE(polling, true) AS polling,
                   bacnet_device_id, object_identifier, object_name, modbus_config
                   FROM points WHERE site_id = ANY(%s::uuid[]) ORDER BY site_id, external_id""",
                (site_ids,),
            )
            points_rows = cur.fetchall()
            cur.execute(
                """SELECT id, site_id, equipment_id, external_id, name, description, calc_type,
                          parameters, point_bindings, enabled
                   FROM energy_calculations WHERE site_id = ANY(%s::uuid[])
                   ORDER BY site_id, external_id""",
                (site_ids,),
            )
            energy_rows = cur.fetchall()

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

    ec_by_site: dict[str, list[dict]] = {}
    for ec in energy_rows:
        ec_by_site.setdefault(str(ec["site_id"]), []).append(ec)

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
            feeds_id = e.get("feeds_equipment_id")
            fed_by_id = e.get("fed_by_equipment_id")
            extra: list[str] = []
            if feeds_id:
                extra.append(f"brick:feeds :eq_{str(feeds_id).replace('-', '_')}")
            if fed_by_id:
                extra.append(f"brick:isFedBy :eq_{str(fed_by_id).replace('-', '_')}")
            if extra:
                lines.append("    " + " ;\n    ".join(extra) + " ;")
            lines.append(f'    ofdd:equipmentType "{etype}"')
            if etype == "Weather_Service" or ename == "Open-Meteo":
                lines.append(' ;')
                lines.append('    ofdd:dataSource "open_meteo" .')
            else:
                lines.append(" .")
            lines.append("")
            _append_equipment_engineering(lines, e, eref)
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

        for ec in ec_by_site.get(sid, []):
            _append_energy_calculation(lines, ec, sref)

    return "\n".join(lines)


def _append_energy_calculation(
    lines: list[str], ec: dict[str, Any], site_ref: str
) -> None:
    """Emit FDD energy / savings calc spec for SPARQL and knowledge-graph export."""
    eid = str(ec["id"]).replace("-", "_")
    uri = f":ec_{eid}"
    label = _escape((ec.get("name") or ec.get("external_id") or "calc"))
    lines.append(f"{uri} a ofdd:EnergyCalculation ;")
    lines.append(f'    rdfs:label "{label}" ;')
    lines.append(f'    ofdd:calcExternalId "{_escape(str(ec.get("external_id") or ""))}" ;')
    lines.append(f'    ofdd:calcType "{_escape(str(ec.get("calc_type") or ""))}" ;')
    lines.append(f"    ofdd:calcEnabled {'true' if ec.get('enabled', True) else 'false'} ;")
    desc = ec.get("description")
    if desc is not None and str(desc).strip():
        lines.append(f'    rdfs:comment "{_escape(str(desc).strip())}" ;')
    params = ec.get("parameters") if isinstance(ec.get("parameters"), dict) else {}
    seq = params.get("_penalty_catalog_seq")
    if seq is not None:
        try:
            lines.append(f'    ofdd:penaltyCatalogSeq {int(seq)} ;')
        except (TypeError, ValueError):
            pass
    pj = json.dumps(params, separators=(",", ":"), sort_keys=True)
    lines.append(f'    ofdd:calcParameters "{_escape(pj)}" ;')
    binds = ec.get("point_bindings") if isinstance(ec.get("point_bindings"), dict) else {}
    bj = json.dumps(binds, separators=(",", ":"), sort_keys=True)
    lines.append(f'    ofdd:calcPointBindings "{_escape(bj)}" ;')
    eq_id = ec.get("equipment_id")
    if eq_id:
        eref = f":eq_{str(eq_id).replace('-', '_')}"
        lines.append(f"    ofdd:forEquipment {eref} ;")
    lines.append(f"    brick:isPartOf {site_ref} .")
    lines.append("")


def _append_equipment_engineering(
    lines: list[str], equipment_row: dict[str, Any], equipment_ref: str
) -> None:
    """Emit engineering metadata as RDF (ofdd extension + s223 topology patterns)."""
    metadata = equipment_row.get("metadata")
    if not isinstance(metadata, dict):
        return
    engineering = metadata.get("engineering")
    if not isinstance(engineering, dict):
        return

    field_to_pred = {
        "control_system_type": "ofdd:controlSystemType",
        "control_vendor": "ofdd:controlVendor",
        "front_end_platform": "ofdd:frontEndPlatform",
        "panel_name": "ofdd:panelName",
        "ip_address": "ofdd:ipAddress",
        "bacnet_network_number": "ofdd:bacnetNetworkNumber",
        "install_date": "ofdd:installDate",
        "as_built_date": "ofdd:asBuiltDate",
        "manufacturer": "ofdd:manufacturer",
        "model_number": "ofdd:modelNumber",
        "serial_number": "ofdd:serialNumber",
        "design_cfm": "ofdd:designCFM",
        "cooling_capacity_tons": "ofdd:coolingCapacityTons",
        "heating_capacity_mbh": "ofdd:heatingCapacityMBH",
        "pump_flow_gpm": "ofdd:pumpFlowGPM",
        "pump_head_ft": "ofdd:pumpHeadFT",
        "electrical_system_voltage": "ofdd:electricalSystemVoltage",
        "fla": "ofdd:fla",
        "mca": "ofdd:mca",
        "mocp": "ofdd:mocp",
        "feeder_panel": "ofdd:feederPanel",
        "feeder_breaker": "ofdd:feederBreaker",
        "source_document_name": "ofdd:sourceDocumentName",
        "source_sheet": "ofdd:sourceSheet",
    }
    for section in ("controls", "mechanical", "electrical", "documents"):
        payload = engineering.get(section)
        if not isinstance(payload, dict):
            continue
        for key, pred in field_to_pred.items():
            val = payload.get(key)
            if val is None or val == "":
                continue
            lines.append(f'{equipment_ref} {pred} "{_escape(str(val))}" .')

    topology = engineering.get("topology")
    if not isinstance(topology, dict):
        return

    raw_eq_id = equipment_row.get("id")
    if not raw_eq_id:
        logger.warning(
            "Skipping engineering RDF for equipment row with empty id: %s",
            equipment_row,
        )
        return
    eq_id = str(raw_eq_id).replace("-", "_")
    connection_points = topology.get("connection_points")
    if isinstance(connection_points, list):
        for idx, cp in enumerate(connection_points):
            if not isinstance(cp, dict):
                continue
            cp_ref = f":cp_{eq_id}_{idx}"
            cp_kind = str(cp.get("type") or "").strip().lower()
            cp_class = "s223:ConnectionPoint"
            if cp_kind == "inlet":
                cp_class = "s223:InletConnectionPoint"
            elif cp_kind == "outlet":
                cp_class = "s223:OutletConnectionPoint"
            lines.append(f"{cp_ref} a {cp_class} .")
            lines.append(f"{equipment_ref} s223:hasConnectionPoint {cp_ref} .")
            if cp.get("name"):
                lines.append(f'{cp_ref} rdfs:label "{_escape(str(cp["name"]))}" .')
            if cp.get("id"):
                lines.append(f'{cp_ref} ofdd:connectionPointId "{_escape(str(cp["id"]))}" .')
            if cp.get("medium"):
                lines.append(f'{cp_ref} ofdd:connectionMedium "{_escape(str(cp["medium"]))}" .')

    connections = topology.get("connections")
    if isinstance(connections, list):
        for idx, cn in enumerate(connections):
            if not isinstance(cn, dict):
                continue
            cn_ref = f":cnx_{eq_id}_{idx}"
            ctype = str(cn.get("conduit_type") or "").strip().lower()
            cn_class = "ofdd:EngineeringConnection"
            if ctype == "duct":
                cn_class = "s223:Duct"
            elif ctype == "pipe":
                cn_class = "s223:Pipe"
            elif ctype in {"wire", "feeder"}:
                cn_class = "s223:Wire"
            lines.append(f"{cn_ref} a {cn_class} .")
            lines.append(f"{equipment_ref} s223:cnx {cn_ref} .")
            if cn.get("from"):
                lines.append(f'{cn_ref} ofdd:connectsFromRef "{_escape(str(cn["from"]))}" .')
            if cn.get("to"):
                lines.append(f'{cn_ref} ofdd:connectsToRef "{_escape(str(cn["to"]))}" .')
            if cn.get("medium"):
                lines.append(f'{cn_ref} ofdd:connectionMedium "{_escape(str(cn["medium"]))}" .')


def _get_unified_ttl_path() -> Path:
    """Path for the single TTL file (Brick + BACnet sections)."""
    path_str = getattr(
        get_platform_settings(), "brick_ttl_path", "config/data_model.ttl"
    )
    p = Path(path_str)
    return (Path.cwd() / p) if not p.is_absolute() else p


def _read_unified_sections(path: Path) -> tuple[str, str | None]:
    """Read unified TTL file; return (brick_section, bacnet_section_or_none)."""
    if not path.exists():
        return "", None
    text = path.read_text(encoding="utf-8")
    if BACNET_SECTION_MARKER not in text:
        return text.rstrip(), None
    brick, _, bacnet = text.partition(BACNET_SECTION_MARKER)
    bacnet = bacnet.lstrip("\n").rstrip()
    return brick.rstrip(), bacnet if bacnet else None


def _remove_legacy_bacnet_scan_ttl(unified_path: Path) -> None:
    """Remove config/bacnet_scan.ttl if it exists (legacy or recreated by old process)."""
    legacy = Path.cwd() / "config" / "bacnet_scan.ttl"
    if legacy.exists() and legacy.resolve() != unified_path.resolve():
        try:
            legacy.unlink()
        except OSError:
            pass


def _get_bacnet_section_cached(path: Path) -> str | None:
    """Return BACnet section, using in-memory cache when path matches to avoid file read."""
    global _bacnet_cache
    if _bacnet_cache is not None and _bacnet_cache[0] == path:
        return _bacnet_cache[1]
    _, bacnet = _read_unified_sections(path)
    _bacnet_cache = (path, bacnet)
    return bacnet


def _do_sync() -> None:
    """Write in-memory graph (Brick from DB + BACnet) to disk via graph_model."""
    global _sync_timer
    try:
        from openfdd_stack.platform.graph_model import write_ttl_to_file
        write_ttl_to_file()
    except Exception:
        pass
    _remove_legacy_bacnet_scan_ttl(_get_unified_ttl_path())
    with _sync_timer_lock:
        _sync_timer = None


def _flush_sync() -> None:
    """Timer callback or atexit: run pending sync only if one was scheduled."""
    global _sync_timer
    with _sync_timer_lock:
        t = _sync_timer
        _sync_timer = None
    if t is not None:
        t.cancel()
        _do_sync()


def sync_ttl_to_file(
    site_id: UUID | None = None,
    *,
    immediate: bool = False,
) -> None:
    """
    Write current DB state as Brick TTL to the unified config file. Preserves any
    BACnet discovery section (from in-memory cache when possible). Path from
    OFDD_BRICK_TTL_PATH. Falls back to /tmp/data_model.ttl if not writable.

    When immediate=False (default), sync is debounced by ~250ms so rapid CRUD
    triggers one write. When immediate=True (e.g. GET /data-model/ttl?save=true),
    writes immediately. File always contains the full model (site_id is ignored
    for the on-disk file).
    """
    global _sync_timer
    if immediate:
        with _sync_timer_lock:
            if _sync_timer is not None:
                _sync_timer.cancel()
                _sync_timer = None
        _do_sync()
        return
    with _sync_timer_lock:
        if _sync_timer is not None:
            _sync_timer.cancel()
        _sync_timer = threading.Timer(0.25, _flush_sync)
        _sync_timer.start()


# Flush any pending sync on process exit so the file is not stale
atexit.register(_flush_sync)

# Remove legacy config/bacnet_scan.ttl on load so an old API process can't leave it behind
def _cleanup_legacy_bacnet_file_on_load() -> None:
    legacy = Path.cwd() / "config" / "bacnet_scan.ttl"
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass


_cleanup_legacy_bacnet_file_on_load()


def get_bacnet_scan_ttl_path() -> Path:
    """Path of the unified TTL file (BACnet section is stored after Brick in same file)."""
    return _get_unified_ttl_path()


def get_bacnet_scan_ttl() -> str | None:
    """Read BACnet discovery section from the unified TTL file (uses cache when set)."""
    path = _get_unified_ttl_path()
    bacnet = _get_bacnet_section_cached(path)
    if bacnet is not None:
        return bacnet
    # One-time migration: merge legacy config/bacnet_scan.ttl into unified file, then remove it
    legacy = Path.cwd() / "config" / "bacnet_scan.ttl"
    if legacy.exists():
        text = legacy.read_text(encoding="utf-8").strip()
        if text:
            store_bacnet_scan_ttl(text)
            try:
                legacy.unlink()
            except OSError:
                pass
            return text
    return None


def store_bacnet_scan_ttl(ttl: str) -> None:
    """
    Merge BACnet TTL into in-memory graph (legacy path; primary path is point_discovery_to_graph).
    Next serialize (interval or route) will write full graph to file.
    """
    try:
        from openfdd_stack.platform.graph_model import merge_bacnet_ttl
        merge_bacnet_ttl(ttl)
    except Exception:
        pass
    global _bacnet_cache
    path = _get_unified_ttl_path()
    _bacnet_cache = (path, ttl.strip())


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
    Parse BACnet RDF TTL into devices and point_discoveries
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
    TTL used for SPARQL: in-memory graph (Brick from DB + BACnet). Single graph for both.
    """
    try:
        from openfdd_stack.platform.graph_model import get_ttl_for_sparql as _graph_ttl
        return _graph_ttl(site_id=site_id)
    except Exception:
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
