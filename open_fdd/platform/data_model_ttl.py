"""
Generate Brick TTL from current DB state (sites, equipment, points).

Single source of truth = DB. TTL is derived for FDD column_map and SPARQL validation.
Points use rdfs:label = external_id (time-series reference) and optional ofdd:mapsToRuleInput = fdd_input.

One unified TTL file (config/brick_model.ttl): Brick section first, then BACnet discovery
section after BACNET_SECTION_MARKER. CRUD and point_discovery_to_graph update the in-memory graph; sync writes this file.
"""

from __future__ import annotations

import atexit
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn

BACNET_SECTION_MARKER = "# --- BACnet discovery ---"

# In-memory cache: (path, bacnet_section) so we avoid reading the file on every sync.
_bacnet_cache: tuple[Path, str | None] | None = None
_sync_timer: threading.Timer | None = None
_sync_timer_lock = threading.Lock()

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
    polling = p.get("polling", True)
    lines.append(f"{pt_uri} a brick:{brick_type} ;")
    lines.append(f'    rdfs:label "{label}" ;')
    lines.append(f"    ofdd:polling {'true' if polling else 'false'} ;")
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
                """SELECT id, site_id, name, equipment_type, feeds_equipment_id, fed_by_equipment_id FROM equipment
                   WHERE site_id = ANY(%s::uuid[]) ORDER BY site_id, name""",
                (site_ids,),
            )
            equipment = cur.fetchall()
            cur.execute(
                """SELECT id, site_id, external_id, brick_type, fdd_input, unit, equipment_id, COALESCE(polling, true) AS polling
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
            feeds_id = e.get("feeds_equipment_id")
            fed_by_id = e.get("fed_by_equipment_id")
            extra: list[str] = []
            if feeds_id:
                extra.append(f"brick:feeds :eq_{str(feeds_id).replace('-', '_')}")
            if fed_by_id:
                extra.append(f"brick:isFedBy :eq_{str(fed_by_id).replace('-', '_')}")
            if extra:
                lines.append("    " + " ;\n    ".join(extra) + " ;")
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


def _get_unified_ttl_path() -> Path:
    """Path for the single TTL file (Brick + BACnet sections)."""
    path_str = getattr(
        get_platform_settings(), "brick_ttl_path", "config/brick_model.ttl"
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
        from open_fdd.platform.graph_model import write_ttl_to_file
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
    OFDD_BRICK_TTL_PATH. Falls back to /tmp/brick_model.ttl if not writable.

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
        from open_fdd.platform.graph_model import merge_bacnet_ttl
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
        from open_fdd.platform.graph_model import get_ttl_for_sparql as _graph_ttl
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
