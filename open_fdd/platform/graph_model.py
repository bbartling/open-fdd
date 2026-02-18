"""
In-memory RDF graph model for Open-FDD: Brick (from DB) + BACnet (from point_discovery).

- Loads config/brick_model.ttl on boot into an rdflib Graph.
- Brick triples are refreshed from DB on sync; BACnet triples are updated from
  point_discovery JSON (clean TTL, no bacpypes repr).
- Single serialize path: graph → TTL string → config/brick_model.ttl.
- Background thread serializes to file at OFDD_GRAPH_SYNC_INTERVAL_MIN (default 5).
- Health exposes last serialization result and timestamps.
"""

from __future__ import annotations

import atexit
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn

BACNET_NS = "http://data.ashrae.org/bacnet/2020#"
BACNET_SECTION_MARKER = "# --- BACnet discovery ---"
BRICK_PREFIX = "https://brickschema.org/schema/Brick#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
OFDD_NS = "http://openfdd.local/ontology#"
SITE_NS = "http://openfdd.local/site#"
XSD_NS = "http://www.w3.org/2001/XMLSchema#"

# In-memory graph (rdflib). Populated on startup from file or DB.
_graph: Any = None
_graph_lock = threading.RLock()

# Serialization state for /health
_last_serialization_ok: bool | None = None
_last_serialization_error: str | None = None
_last_serialization_at: datetime | None = None
_serialization_lock = threading.Lock()

_sync_thread: threading.Thread | None = None
_sync_stop = threading.Event()


def _get_ttl_path() -> Path:
    path_str = getattr(
        get_platform_settings(), "brick_ttl_path", "config/brick_model.ttl"
    )
    p = Path(path_str)
    return (Path.cwd() / p) if not p.is_absolute() else p


def _escape(s: str) -> str:
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _prefixes_ttl() -> str:
    return """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix : <http://openfdd.local/site#> .

"""


def build_brick_ttl_from_db(site_id: UUID | None = None) -> str:
    """Build Brick TTL from DB (sites, equipment, points). Same logic as data_model_ttl.build_ttl_from_db."""
    from open_fdd.platform.data_model_ttl import build_ttl_from_db

    return build_ttl_from_db(site_id=site_id)


def bacnet_ttl_from_point_discovery(
    device_instance: int,
    device_address: str,
    objects: list[dict],
    *,
    device_name: str | None = None,
) -> str:
    """
    Build clean BACnet RDF TTL from point_discovery JSON (no bacpypes repr).
    objects: list of { object_identifier, object_name, description?, present_value?, units? }.
    """
    lines = []
    base = f"bacnet://{device_instance}"
    dev_uri = f"<{base}>"
    dev_label = device_name or f"BACnet device {device_instance}"
    lines.append(f"{dev_uri} a bacnet:Device ;")
    lines.append(f'    rdfs:label "{_escape(dev_label)}" ;')
    lines.append(
        f'    bacnet:device-address [ rdfs:label "{_escape(device_address)}" ] ;'
    )
    lines.append(f"    bacnet:device-instance {device_instance} ;")
    obj_refs = []
    for o in objects:
        oid = (o.get("object_identifier") or o.get("name") or "").strip()
        if not oid:
            continue
        obj_uri = f"<{base}/{oid}>"
        obj_refs.append(obj_uri)
    if obj_refs:
        lines.append("    bacnet:contains " + ",\n        ".join(obj_refs) + " .")
    else:
        # Last line was "    bacnet:device-instance N ;" -> end with " ."
        lines[-1] = lines[-1].rstrip().rstrip(";").rstrip() + " ."
    lines.append("")

    for o in objects:
        oid = (o.get("object_identifier") or o.get("name") or "").strip()
        if not oid:
            continue
        obj_uri = f"<{base}/{oid}>"
        oname = (o.get("object_name") or o.get("name") or oid.replace(",", "_")).strip()
        parts = [
            f'bacnet:object-identifier "{_escape(oid)}"',
            f'bacnet:object-name "{_escape(oname)}"',
        ]
        if o.get("description"):
            parts.append(f'bacnet:description "{_escape(str(o["description"]))}"')
        lines.append(f"{obj_uri} " + " ;\n    ".join(parts) + " .")
        lines.append("")

    prefix_block = """@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

"""
    return prefix_block + "\n".join(lines)


def _ensure_graph() -> Any:
    global _graph
    with _graph_lock:
        if _graph is None:
            from rdflib import Graph

            _graph = Graph()
            _graph.bind("bacnet", BACNET_NS)
            _graph.bind("brick", BRICK_PREFIX)
            _graph.bind("rdfs", RDFS_NS)
            _graph.bind("ofdd", OFDD_NS)
            _graph.bind("", SITE_NS)
        return _graph


def load_from_file() -> None:
    """Load unified brick_model.ttl into in-memory graph on boot (Brick + BACnet sections)."""
    path = _get_ttl_path()
    g = _ensure_graph()
    with _graph_lock:
        g.remove((None, None, None))
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                brick_part = text
                bacnet_part = None
                if BACNET_SECTION_MARKER in text:
                    brick_part, _, rest = text.partition(BACNET_SECTION_MARKER)
                    brick_part = brick_part.rstrip()
                    bacnet_part = rest.lstrip("\n").strip()
                if brick_part.strip():
                    g.parse(data=brick_part, format="turtle")
                if bacnet_part and bacnet_part.strip():
                    g.parse(data=bacnet_part, format="turtle")
            except Exception:
                pass
        if len(g) == 0:
            brick_ttl = build_brick_ttl_from_db(site_id=None)
            if brick_ttl.strip():
                g.parse(data=brick_ttl, format="turtle")


def sync_brick_from_db() -> None:
    """Replace Brick triples in the graph with current DB state (sites, equipment, points)."""
    from rdflib import Namespace, URIRef

    g = _ensure_graph()
    site_ns = Namespace(SITE_NS)
    brick_ns = Namespace(BRICK_PREFIX)
    with _graph_lock:
        to_remove = [
            (s, p, o)
            for s, p, o in g
            if isinstance(s, URIRef) and str(s).startswith(SITE_NS)
        ]
        for t in to_remove:
            g.remove(t)
        brick_ttl = build_brick_ttl_from_db(site_id=None)
        if brick_ttl.strip():
            g.parse(data=brick_ttl, format="turtle")


def _bacnet_subjects(g: Any) -> set:
    from rdflib import URIRef

    bacnet_uri = "http://data.ashrae.org/bacnet/"
    return {
        s
        for s in g.subjects()
        if isinstance(s, URIRef) and str(s).startswith(bacnet_uri)
    }


def merge_bacnet_ttl(ttl: str) -> None:
    """
    Parse BACnet TTL and merge into in-memory graph.
    Removes existing BACnet triples (subjects with bacnet: URI), then adds triples from ttl.
    """
    from rdflib import Graph, URIRef

    g = _ensure_graph()
    with _graph_lock:
        to_remove = [
            (s, p, o)
            for s, p, o in g
            if (isinstance(s, URIRef) and str(s).startswith("bacnet://"))
            or (isinstance(o, URIRef) and str(o).startswith("bacnet://"))
        ]
        for t in to_remove:
            g.remove(t)
        if ttl and ttl.strip():
            temp = Graph()
            temp.parse(data=ttl, format="turtle")
            for t in temp:
                g.add(t)


def update_bacnet_from_point_discovery(
    device_instance: int,
    device_address: str,
    objects: list[dict],
    *,
    device_name: str | None = None,
) -> None:
    """
    Update in-memory graph with BACnet device from point_discovery JSON.
    Removes existing BACnet triples for this device, adds clean triples from objects.
    """
    from rdflib import Graph, Namespace, URIRef

    g = _ensure_graph()
    bacnet_ns = Namespace(BACNET_NS)
    base_uri = f"bacnet://{device_instance}"
    with _graph_lock:
        to_remove = [
            (s, p, o)
            for s, p, o in g
            if isinstance(s, URIRef)
            and str(s).startswith(base_uri)
            or (isinstance(o, URIRef) and str(o).startswith(base_uri))
        ]
        for t in to_remove:
            g.remove(t)
        ttl = bacnet_ttl_from_point_discovery(
            device_instance, device_address, objects, device_name=device_name
        )
        temp = Graph()
        temp.parse(data=ttl, format="turtle")
        for t in temp:
            g.add(t)


def serialize_to_ttl() -> str:
    """Produce full TTL string from in-memory graph (Brick + BACnet)."""
    sync_brick_from_db()
    g = _ensure_graph()
    with _graph_lock:
        out = g.serialize(format="turtle")
    return out.decode("utf-8") if isinstance(out, bytes) else out


def write_ttl_to_file() -> tuple[bool, str | None]:
    """
    Serialize graph to TTL and write to config/brick_model.ttl.
    Returns (success, error_message). Updates health state.
    """
    global _last_serialization_ok, _last_serialization_error, _last_serialization_at
    try:
        ttl = serialize_to_ttl()
        path = _get_ttl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ttl, encoding="utf-8")
        with _serialization_lock:
            _last_serialization_ok = True
            _last_serialization_error = None
            _last_serialization_at = datetime.now(timezone.utc)
        return True, None
    except Exception as e:
        err = str(e)
        with _serialization_lock:
            _last_serialization_ok = False
            _last_serialization_error = err
            _last_serialization_at = datetime.now(timezone.utc)
        return False, err


def get_serialization_status() -> dict:
    """For /health: last result, error if any, last time, current time."""
    with _serialization_lock:
        ok = _last_serialization_ok
        err = _last_serialization_error
        at = _last_serialization_at
    now = datetime.now(timezone.utc)
    return {
        "graph_serialization": {
            "last_ok": ok,
            "last_error": err,
            "last_serialization_at": at.isoformat() if at else None,
            "current_time": now.isoformat(),
        }
    }


def get_ttl_for_sparql(site_id: UUID | None = None) -> str:
    """TTL string for SPARQL: full in-memory graph (Brick from DB + BACnet)."""
    return serialize_to_ttl()


def _sync_loop() -> None:
    """Background: every N minutes serialize graph to file."""
    settings = get_platform_settings()
    interval_min = getattr(settings, "graph_sync_interval_min", 5) or 5
    interval_sec = max(60, interval_min * 60)
    while not _sync_stop.wait(timeout=interval_sec):
        write_ttl_to_file()


def start_sync_thread() -> None:
    """Start background thread that serializes graph to file periodically."""
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return
    _sync_stop.clear()
    _sync_thread = threading.Thread(target=_sync_loop, daemon=True)
    _sync_thread.start()


def stop_sync_thread() -> None:
    _sync_stop.set()


def get_graph_model() -> Any:
    """Return the in-memory rdflib Graph (for tests or introspection)."""
    return _ensure_graph()
