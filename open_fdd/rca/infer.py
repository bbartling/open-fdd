"""Opt-in, read-only topology inference for sparse HVAC RDF graphs.

Proposes candidate ``s223:connectedTo`` edges when a site model lacks explicit equipment-to-
equipment feeder links. Combines three signals:

1. Directed HVAC equipment role and fluid/air medium compatibility (Brick/Haystack/223P
   tags and generic point tags — e.g. ``boiler -> loop -> ahu``, ``chiller -> loop -> ahu``,
   ``ahu -> vav -> zone``).
2. Lagged cross-correlation / co-movement between upstream supply/discharge/plant points
   and downstream entering/supply/zone/coil points over aligned telemetry.
3. Optional naming-similarity hints (shared unit numbers or tokens).

Inferred edges are strictly advisory, discounted during RCA ranking, clearly labeled
``inferred, not modeled``, and never written back to any RDF model or database.
Suggested links can be exported to CSV or Turtle for human review.
"""

from __future__ import annotations

import csv
import itertools
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from open_fdd.ontology_audit.terms import PREFIXES, split_iri
from open_fdd.rca.evidence import parse_utc
from open_fdd.rca.graph import GraphNode, TopologyGraph

BRICK = PREFIXES["brick"]
PH_IOT = PREFIXES["phIoT"]

# Physical directed equipment flow rules: (upstream_role, downstream_role) -> structural score
ALLOWED_ROLE_FLOWS: dict[tuple[str, str], float] = {
    ("weather", "ahu"): 0.70,
    ("weather", "chiller"): 0.65,
    ("weather", "boiler"): 0.65,
    ("weather", "cooling_tower"): 0.70,
    ("cooling_tower", "loop"): 0.90,
    ("cooling_tower", "chiller"): 0.80,
    ("chiller", "loop"): 0.92,
    ("chiller", "ahu"): 0.78,
    ("boiler", "loop"): 0.92,
    ("boiler", "ahu"): 0.78,
    ("boiler", "vav"): 0.74,
    ("pump", "loop"): 0.82,
    ("pump", "ahu"): 0.68,
    ("loop", "ahu"): 0.92,
    ("loop", "vav"): 0.88,
    ("ahu", "vav"): 0.95,
    ("ahu", "zone"): 0.88,
    ("vav", "zone"): 0.95,
}

# Stopwords ignored in naming-similarity hints
_NAME_STOPWORDS = frozenset(
    {
        "equip",
        "equipment",
        "ahu",
        "rtu",
        "vav",
        "zone",
        "room",
        "boiler",
        "chiller",
        "pump",
        "loop",
        "tower",
        "cooling",
        "primary",
        "secondary",
        "chilled",
        "hot",
        "water",
        "condenser",
        "steam",
        "air",
        "unit",
        "system",
        "plant",
        "main",
    }
)


@dataclass(frozen=True)
class InferredEdge:
    """Proposed ``s223:connectedTo`` edge inferred from telemetry, role tags, and naming hints."""

    upstream_iri: str
    downstream_iri: str
    upstream_id: str
    downstream_id: str
    upstream_label: str
    downstream_label: str
    predicate: str = "s223:connectedTo"
    confidence: float = 0.0
    structural_score: float = 0.0
    telemetry_score: float = 0.0
    naming_score: float = 0.0
    correlation: float | None = None
    lag_steps: int | None = None
    n_samples: int = 0
    upstream_point: str = ""
    downstream_point: str = ""
    upstream_role: str = ""
    downstream_role: str = ""
    evidence: tuple[str, ...] = ()
    inferred: bool = True


def _tag_tokens(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for val in values:
        _, local = split_iri(val)
        if local:
            tokens.add(local.lower())
            tokens.update(_word_tokens(local))
    return tokens


def _word_tokens(text: str) -> set[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    raw = re.findall(r"[a-zA-Z0-9]+", spaced.lower())
    out: set[str] = set()
    for tok in raw:
        out.add(tok)
        # Also split alpha+digits like "ahu10" -> "ahu", "10"
        m = re.match(r"^([a-z]+)(\d+)$", tok)
        if m:
            out.add(m.group(1))
            out.add(m.group(2))
    return out


def _equip_points(graph: TopologyGraph) -> dict[str, list[GraphNode]]:
    """Map equipment IRI -> point nodes via ``s223:hasProperty`` or a Haystack ``equipRef`` overlay."""
    pts: dict[str, list[GraphNode]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for node in graph.nodes.values():
        if not node.is_point:
            continue
        for edge in graph.upstream_edges.get(node.iri, ()):
            if edge.predicate in ("phIoT:equipRef", "s223:hasProperty", "brick:isPointOf"):
                key = (edge.upstream_iri, node.iri)
                if key not in seen and edge.upstream_iri in graph.nodes:
                    seen.add(key)
                    pts[edge.upstream_iri].append(node)

    if graph.rdflib_graph is not None:
        from rdflib import URIRef

        for pred in (URIRef(BRICK + "hasPoint"), URIRef(BRICK + "isPointOf")):
            for s, _, o in graph.rdflib_graph.triples((None, pred, None)):
                if not (isinstance(s, URIRef) and isinstance(o, URIRef)):
                    continue
                s_s, o_s = str(s), str(o)
                if pred.endswith("hasPoint"):
                    eq_iri, pt_iri = s_s, o_s
                else:
                    pt_iri, eq_iri = s_s, o_s
                pt_node = graph.nodes.get(pt_iri)
                if pt_node is not None and eq_iri in graph.nodes:
                    key = (eq_iri, pt_iri)
                    if key not in seen:
                        seen.add(key)
                        pts[eq_iri].append(pt_node)
    return pts


def _classify_equipment(node: GraphNode, pts: Sequence[GraphNode]) -> tuple[str, set[str]]:
    """Infer generic HVAC role and fluid/air media set from RDF types, tags, and label."""
    eq_toks = _tag_tokens((*node.equip_types, *node.tags))
    pt_toks = _tag_tokens(t for p in pts for t in (*p.equip_types, *p.tags))
    lbl_toks = _word_tokens(node.label) | _word_tokens(node.node_id)
    pt_lbl_toks = {t for p in pts for t in (_word_tokens(p.label) | _word_tokens(p.node_id))}

    media: set[str] = set()
    if (
        "chilledwatercool" in eq_toks
        or "chilled" in pt_toks
        or "chw" in (lbl_toks | pt_lbl_toks)
    ):
        media.add("chw")
    if (
        "hotwaterheat" in eq_toks
        or "hotwaterreheat" in eq_toks
        or "primaryloop" in eq_toks
        or "hot" in pt_toks
        or "reheat" in pt_toks
        or "boiler" in eq_toks
        or "boiler" in pt_toks
        or "hw" in (lbl_toks | pt_lbl_toks)
    ):
        media.add("hw")
    if (
        "condenser" in pt_toks
        or "condenser" in lbl_toks
        or "cond" in pt_lbl_toks
        or "coolingtower" in pt_toks
    ):
        media.add("cw")
    if "steam" in pt_toks or "steam" in lbl_toks or "condensate" in pt_toks:
        media.add("steam")
    if "domestichot" in pt_toks or "dhw" in (lbl_toks | pt_lbl_toks):
        media.add("dhw")

    if "weatherstation" in eq_toks or "weather" in eq_toks or "weather" in lbl_toks:
        return "weather", media
    if "chiller" in eq_toks or "chiller" in pt_toks or "chiller" in lbl_toks:
        return "chiller", media | {"chw"}
    if "boiler" in eq_toks or "boiler" in lbl_toks:
        return "boiler", media | {"hw"}
    if (
        "coolingtower" in eq_toks
        or "cooling_tower" in eq_toks
        or "coolingtower" in pt_toks
    ):
        return "cooling_tower", media | {"cw"}
    if (
        "ahu" in eq_toks
        or "air_handling_unit" in eq_toks
        or "airhandlingunit" in eq_toks
        or "rtu" in eq_toks
        or "rooftop" in eq_toks
        or "ahu" in lbl_toks
        or "rtu" in lbl_toks
    ):
        return "ahu", media | {"air"}
    if (
        "vav" in eq_toks
        or "terminalunit" in eq_toks
        or "fanpoweredbox" in eq_toks
        or "vav" in lbl_toks
    ):
        return "vav", media | {"air"}
    if (
        "hvac_zone" in eq_toks
        or "zone" in eq_toks
        or "space" in eq_toks
        or "room" in eq_toks
        or "zone" in lbl_toks
    ):
        return "zone", media | {"air"}
    if "pump" in eq_toks or "pump" in pt_toks or "pump" in lbl_toks:
        if "condensate" in pt_toks or "condensate" in pt_lbl_toks:
            return "pump_condensate", media
        return "pump", media
    if "primaryloop" in eq_toks or "loop" in eq_toks or "loop" in lbl_toks:
        return "loop", media
    return "other", media


def _classify_point(point: GraphNode) -> tuple[str, str]:
    """Return ``(signal_role, medium)`` or ``('ignore', '')`` for setpoints/non-causal channels."""
    toks = _tag_tokens((*point.equip_types, *point.tags))
    lbl = _word_tokens(point.label) | _word_tokens(point.node_id)
    all_t = toks | lbl

    # Exclude setpoints so constant/scheduled setpoints never drive fake topology links
    if "sp" in toks or "setpoint" in all_t or lbl & {"sp", "setpt"}:
        return "ignore", ""
    # Exclude humidity / humidifier / static pressure / occupancy
    if all_t & {"humidity", "humidifier", "rah", "humv", "enthalpy", "co2", "occupancy"}:
        return "ignore", ""

    medium = ""
    if "chilled" in toks or "chw" in lbl or "cvc" in lbl or "cooling" in toks:
        medium = "chw"
    elif "hot" in toks or "reheat" in toks or "boiler" in all_t or "hw" in lbl or "hvc" in lbl:
        medium = "hw"
    elif "condenser" in all_t or "cond" in lbl or "coolingtower" in toks:
        medium = "cw"
    elif "air" in toks or any(k in lbl for k in ("sat", "dat", "mat", "rat", "znt", "eat")):
        medium = "air"
    elif "water" in toks or any(k in lbl for k in ("swt", "rwt", "b1", "b2", "b3")):
        medium = "water"

    is_temp = bool(toks & {"temp", "temperature"}) or bool(lbl & {"temp", "temperature", "sat", "dat", "mat", "rat", "znt", "swt", "rwt", "oat", "eat"})
    if is_temp:
        if "outside" in all_t or "oat" in lbl or "weather" in all_t:
            return "temp_outside", "air"
        if medium == "air" or any(k in lbl for k in ("sat", "dat", "mat", "rat", "znt", "eat")):
            if toks & {"discharge", "supply", "leaving"} or lbl & {"sat", "dat"}:
                return "temp_air_out", "air"
            if toks & {"entering", "mixed", "return", "zone", "room"} or lbl & {"mat", "rat", "znt", "eat"}:
                return "temp_air_in", "air"
            return "temp_air_generic", "air"
        if "water" in toks or "boiler" in all_t or lbl & {"swt", "rwt"}:
            if toks & {"return", "entering"} or "rwt" in lbl:
                return "temp_water_in", medium or "water"
            return "temp_water_out", medium or "water"
        if "tank" in all_t:
            return "temp_water_out", medium or "water"

    if "valve" in all_t or "cvc" in lbl or "hvc" in lbl or "reheat" in toks:
        if "bypass" in all_t:
            return "loop_state", medium or "water"
        if medium == "chw" or "cooling" in toks or "cvc" in lbl:
            return "coil_valve_chw", "chw"
        if medium == "hw" or "heating" in toks or "reheat" in toks or "hvc" in lbl:
            return "coil_valve_hw", "hw"
        return "coil_valve", medium or "water"

    if "damper" in all_t or "airflow" in all_t or "flow" in toks:
        return "air_flow", "air"

    if all_t & {"status", "run", "load", "power", "capacity", "speed", "vfd"}:
        return "plant_state", medium

    if "differential" in all_t or "dp" in lbl:
        return "loop_state", medium or "water"

    return "ignore", ""


def _media_compatible(u_role: str, u_media: set[str], d_role: str, d_media: set[str]) -> bool:
    if u_role == "cooling_tower" and d_role == "loop":
        return "cw" in d_media
    if u_role == "chiller" and d_role == "loop":
        return "chw" in d_media
    if u_role == "boiler" and d_role == "loop":
        return bool({"hw", "steam"} & d_media)
    if u_role == "pump":
        return bool(u_media & d_media)
    if u_role == "loop" and d_role in ("ahu", "vav"):
        return bool({"chw", "hw"} & u_media & d_media)
    if u_role == "chiller" and d_role == "ahu":
        return "chw" in d_media or not ({"chw", "hw"} & d_media)
    if u_role == "boiler" and d_role in ("ahu", "vav"):
        return "hw" in d_media or not ({"chw", "hw"} & d_media)
    return True


def _signal_pair_allowed(
    u_role: str,
    u_sig: str,
    u_pt_med: str,
    d_role: str,
    d_sig: str,
    d_pt_med: str,
) -> tuple[bool, bool]:
    """Return ``(allowed, require_positive)`` for an upstream/downstream signal pair.

    Air-side discharge/supply to terminal or zone temperatures require a positive
    correlation. Plant/loop/coil pairs may move inversely (chiller leaving or
    capacity vs loop temperature, valve or status vs coil/loop temperature), so
    ``require_positive`` is False and the signed coefficient is kept as evidence.
    """
    if u_sig == "ignore" or d_sig == "ignore":
        return False, False

    if u_role == "weather":
        return u_sig == "temp_outside", False

    if u_role in ("ahu", "vav") and d_role in ("vav", "zone"):
        if u_sig in ("temp_air_out", "temp_air_generic") and d_sig in (
            "temp_air_in",
            "temp_air_out",
            "temp_air_generic",
        ):
            return True, True
        if u_sig in ("temp_air_out", "air_flow") and d_sig in ("air_flow", "temp_air_in"):
            return True, False
        return False, False

    if u_role in ("chiller", "boiler", "cooling_tower", "pump") and d_role in ("loop", "chiller"):
        if u_sig in ("temp_water_out", "temp_water_in", "plant_state") and d_sig in (
            "temp_water_out",
            "temp_water_in",
            "loop_state",
            "plant_state",
        ):
            return True, False
        return False, False

    if u_role in ("loop", "boiler", "chiller", "pump") and d_role in ("ahu", "vav"):
        if u_sig not in ("temp_water_out", "temp_water_in", "loop_state", "plant_state"):
            return False, False
        if d_sig == "coil_valve_chw":
            return (u_pt_med in ("", "chw", "water") and u_role in ("loop", "chiller", "pump")), False
        if d_sig == "coil_valve_hw":
            return (u_pt_med in ("", "hw", "water") and u_role in ("loop", "boiler", "pump")), False
        if d_sig in ("temp_air_out", "temp_air_in", "temp_air_generic"):
            return True, False
        return False, False

    return False, False


def _naming_similarity(u: GraphNode, d: GraphNode) -> float:
    u_toks = (_word_tokens(u.label) | _word_tokens(u.node_id)) - _NAME_STOPWORDS
    d_toks = (_word_tokens(d.label) | _word_tokens(d.node_id)) - _NAME_STOPWORDS
    if not u_toks or not d_toks:
        return 0.0
    shared = u_toks & d_toks
    if not shared:
        return 0.0
    # Shared numeric or designator tokens are strong hints
    bonus = 0.25 if any(tok.isdigit() or len(tok) >= 3 for tok in shared) else 0.0
    jaccard = len(shared) / len(u_toks | d_toks)
    return round(min(1.0, jaccard + bonus), 3)


def _pearson_lag(
    xs: list[float | None],
    ys: list[float | None],
    lag: int,
    *,
    min_samples: int,
) -> tuple[float, int]:
    if lag > 0:
        a, b = xs[:-lag], ys[lag:]
    elif lag < 0:
        a, b = xs[-lag:], ys[:lag]
    else:
        a, b = xs, ys
    pairs = [(u, v) for u, v in zip(a, b) if u is not None and v is not None]
    n = len(pairs)
    if n < min_samples:
        return 0.0, n
    mx = sum(u for u, _ in pairs) / n
    my = sum(v for _, v in pairs) / n
    vx = sum((u - mx) ** 2 for u, _ in pairs)
    vy = sum((v - my) ** 2 for _, v in pairs)
    if vx <= 1e-9 or vy <= 1e-9:
        return 0.0, n
    cov = sum((u - mx) * (v - my) for u, v in pairs)
    return cov / math.sqrt(vx * vy), n


TelemetryKey = tuple[str, str]
TelemetryMap = Mapping[str | TelemetryKey, Sequence[tuple[datetime, float]]]


def _telemetry_key(site: str | None, point: str) -> TelemetryKey:
    """Return a (site, point) series key; site is empty when unknown."""
    return ((site or "").strip(), point)


def _split_telemetry_key(key: str | TelemetryKey) -> TelemetryKey:
    """Split a loader key or a bare point id into (site, point)."""
    if isinstance(key, tuple) and len(key) == 2:
        return (str(key[0] or "").strip(), str(key[1]))
    return ("", str(key))


def _align_series(
    telemetry: Mapping[str, Sequence[tuple[datetime, float]]],
    bucket_seconds: int | None,
) -> tuple[dict[str, list[float | None]], int]:
    """Align point telemetry onto a common sorted timestamp grid."""
    all_stamps: list[datetime] = sorted(
        {ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC) for pts in telemetry.values() for ts, _ in pts}
    )
    if not all_stamps:
        return {}, 900

    if bucket_seconds is None:
        diffs = [
            int((b - a).total_seconds())
            for a, b in itertools.pairwise(all_stamps)
            if (b - a).total_seconds() >= 1.0
        ]
        if diffs:
            diffs.sort()
            bucket_seconds = max(1, diffs[len(diffs) // 2])
        else:
            bucket_seconds = 900

    buckets_by_pt: dict[str, dict[int, float]] = {}
    grid_set: set[int] = set()
    for pt_key, samples in telemetry.items():
        slot: dict[int, list[float]] = defaultdict(list)
        for ts, val in samples:
            if val is None or not math.isfinite(val):
                continue
            dt = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
            b = int(dt.timestamp()) // bucket_seconds
            slot[b].append(float(val))
            grid_set.add(b)
        if slot:
            buckets_by_pt[pt_key] = {b: sum(vs) / len(vs) for b, vs in slot.items()}

    grid = sorted(grid_set)
    idx = {b: i for i, b in enumerate(grid)}
    aligned: dict[str, list[float | None]] = {}
    for pt_key, bmap in buckets_by_pt.items():
        arr: list[float | None] = [None] * len(grid)
        for b, val in bmap.items():
            arr[idx[b]] = val
        nums = [v for v in arr if v is not None]
        if len(nums) >= 2:
            mean = sum(nums) / len(nums)
            std = math.sqrt(sum((v - mean) ** 2 for v in nums) / len(nums))
            if std > 1e-6:
                aligned[pt_key] = arr
    return aligned, bucket_seconds


def _resolve_telemetry_to_points(
    graph: TopologyGraph,
    telemetry: TelemetryMap,
    *,
    site_id: str | None = None,
) -> dict[str, Sequence[tuple[datetime, float]]]:
    """Map telemetry keys (point id, openfddKey, IRI, label) to canonical point IRIs.

    Series are resolved with their own site when the key carries one, so identical
    point keys at different sites never share a series or a resolved point.
    """
    resolved: dict[str, list[tuple[datetime, float]]] = {}
    resolved_site: dict[str, str] = {}
    for key, samples in telemetry.items():
        series_site, point = _split_telemetry_key(key)
        if not point:
            continue
        scope = series_site or site_id or None
        node = graph.resolve_node(point, site_id=scope)
        if node is None or not node.is_point:
            continue
        prev_site = resolved_site.get(node.iri)
        if prev_site and series_site and prev_site.lower() != series_site.lower():
            continue
        if node.iri in resolved:
            resolved[node.iri].extend(samples)
        else:
            resolved[node.iri] = list(samples)
            resolved_site[node.iri] = series_site
    return resolved


def infer_topology(
    graph: TopologyGraph,
    telemetry: TelemetryMap,
    *,
    site_id: str | None = None,
    min_correlation: float = 0.50,
    max_lag: int = 3,
    min_samples: int = 24,
    max_feeders_per_domain: int = 4,
    bucket_seconds: int | None = None,
) -> list[InferredEdge]:
    """Propose candidate ``s223:connectedTo`` edges without modifying ``graph``.

    Requires both directed HVAC role/medium compatibility and telemetry co-movement
    (lagged cross-correlation ``>= min_correlation`` over at least ``min_samples``
    aligned observations). Naming similarity acts as a bounded secondary hint.
    """
    pts_by_eq = _equip_points(graph)
    equips = [
        n
        for n in graph.nodes.values()
        if not n.is_point
        and "site" not in _tag_tokens((*n.equip_types, *n.tags))
        and (not site_id or site_id.lower() in graph._site_tokens(n))
    ]
    if len(equips) < 2:
        return []

    by_pt_iri = _resolve_telemetry_to_points(graph, telemetry, site_id=site_id)
    aligned, step_s = _align_series(by_pt_iri, bucket_seconds)
    if not aligned:
        return []

    roles: dict[str, tuple[str, set[str]]] = {}
    for eq in equips:
        roles[eq.iri] = _classify_equipment(eq, pts_by_eq.get(eq.iri, ()))

    pt_classes: dict[str, tuple[str, str]] = {}
    for pts in pts_by_eq.values():
        for pt in pts:
            if pt.iri in aligned:
                pt_classes[pt.iri] = _classify_point(pt)

    modeled_pairs = {
        (e.upstream_iri, e.downstream_iri)
        for edges in graph.upstream_edges.values()
        for e in edges
    }

    candidates: list[InferredEdge] = []
    for u in equips:
        u_role, u_media = roles[u.iri]
        if u_role == "other":
            continue
        u_pts = [p for p in pts_by_eq.get(u.iri, ()) if p.iri in aligned]
        if not u_pts:
            continue

        for d in equips:
            if u.iri == d.iri or (u.iri, d.iri) in modeled_pairs:
                continue
            if u.site_iri and d.site_iri:
                if u.site_iri != d.site_iri:
                    continue
            else:
                u_ids = {t.lower() for t in (u.site_id, *u.site_ids) if t and t.lower() not in {"site"}}
                d_ids = {t.lower() for t in (d.site_id, *d.site_ids) if t and t.lower() not in {"site"}}
                if u_ids and d_ids and not (u_ids & d_ids):
                    continue
            d_role, d_media = roles[d.iri]
            struct = ALLOWED_ROLE_FLOWS.get((u_role, d_role))
            if struct is None or not _media_compatible(u_role, u_media, d_role, d_media):
                continue
            d_pts = [p for p in pts_by_eq.get(d.iri, ()) if p.iri in aligned]
            if not d_pts:
                continue

            best: tuple[float, float, int, int, GraphNode, GraphNode, bool] | None = None
            for pu in u_pts:
                u_sig, u_pmed = pt_classes.get(pu.iri, ("ignore", ""))
                for pd in d_pts:
                    d_sig, d_pmed = pt_classes.get(pd.iri, ("ignore", ""))
                    allowed, req_pos = _signal_pair_allowed(u_role, u_sig, u_pmed, d_role, d_sig, d_pmed)
                    if not allowed or pu.iri == pd.iri:
                        continue
                    for lag in range(max(0, max_lag) + 1):
                        r, n = _pearson_lag(aligned[pu.iri], aligned[pd.iri], lag, min_samples=min_samples)
                        if n < min_samples:
                            continue
                        if req_pos and r < min_correlation:
                            continue
                        if not req_pos and abs(r) < min_correlation:
                            continue
                        # Small preference for positive lag (upstream leads downstream) and higher |r|
                        score = abs(r) + (0.02 if lag > 0 else 0.0)
                        if best is None or score > best[0]:
                            best = (score, r, lag, n, pu, pd, req_pos)

            if best is None:
                continue

            _, r_best, lag_best, n_best, pu_best, pd_best, req_pos = best
            tele_score = min(1.0, abs(r_best))
            name_score = _naming_similarity(u, d)
            lag_bonus = 0.04 if lag_best > 0 else 0.0
            raw_conf = 0.55 * tele_score + 0.30 * struct + 0.11 * name_score + lag_bonus
            conf = round(max(0.05, min(0.95, raw_conf)), 3)
            u_sig_best, _ = pt_classes.get(pu_best.iri, ("ignore", ""))
            d_sig_best, _ = pt_classes.get(pd_best.iri, ("ignore", ""))
            lag_min = lag_best * step_s // 60
            sign_note = (
                "positive correlation required"
                if req_pos
                else "signed; inverse co-movement allowed for this signal type"
            )

            ev_list = [
                f"role pair: {u_role} -> {d_role} (inferred, not modeled)",
                (
                    f"lagged correlation r={r_best:+.3f} ({sign_note}) at lag +{lag_best} "
                    f"({lag_min} min) over {n_best} samples: "
                    f"{pu_best.label} ({u_sig_best}) -> {pd_best.label} ({d_sig_best})"
                ),
            ]
            if r_best < 0:
                ev_list.append(
                    "negative correlation is expected for this pair: plant leaving temperature, "
                    "capacity/status, or valve position may move opposite a loop or coil temperature; "
                    f"accepted because {u_sig_best} -> {d_sig_best} ({u_role} -> {d_role}) does not require a positive sign"
                )
            if name_score > 0:
                ev_list.append(f"naming similarity hint={name_score:.2f}")

            candidates.append(
                InferredEdge(
                    upstream_iri=u.iri,
                    downstream_iri=d.iri,
                    upstream_id=u.node_id,
                    downstream_id=d.node_id,
                    upstream_label=u.label,
                    downstream_label=d.label,
                    confidence=conf,
                    structural_score=round(struct, 3),
                    telemetry_score=round(tele_score, 3),
                    naming_score=name_score,
                    correlation=round(r_best, 3),
                    lag_steps=lag_best,
                    n_samples=n_best,
                    upstream_point=pu_best.label,
                    downstream_point=pd_best.label,
                    upstream_role=u_role,
                    downstream_role=d_role,
                    evidence=tuple(ev_list),
                )
            )

    # Cap feeders first, then drop shortcuts only if the bridge path survived the cap
    grouped: dict[tuple[str, str], list[InferredEdge]] = defaultdict(list)
    for edge in candidates:
        cap_key = edge.upstream_role
        if edge.upstream_role == "loop":
            u_media = roles[edge.upstream_iri][1]
            cap_key = "loop:" + ",".join(sorted(u_media & {"chw", "hw", "cw", "steam"}))
        grouped[(edge.downstream_iri, cap_key)].append(edge)

    kept: list[InferredEdge] = []
    for (dn_iri, cap_key), bucket in grouped.items():
        bucket.sort(key=lambda e: (-e.confidence, -abs(e.correlation or 0.0), e.upstream_label))
        limit = 1 if cap_key in ("ahu", "vav") else max(1, max_feeders_per_domain)
        kept.extend(bucket[:limit])

    loop_in: dict[str, set[str]] = defaultdict(set)
    loop_out: dict[str, set[str]] = defaultdict(set)
    vav_in: dict[str, set[str]] = defaultdict(set)
    vav_out: dict[str, set[str]] = defaultdict(set)
    for edge in kept:
        if edge.downstream_role == "loop":
            loop_in[edge.downstream_iri].add(edge.upstream_iri)
        if edge.upstream_role == "loop":
            loop_out[edge.upstream_iri].add(edge.downstream_iri)
        if edge.downstream_role == "vav" and edge.upstream_role == "ahu":
            vav_in[edge.downstream_iri].add(edge.upstream_iri)
        if edge.upstream_role == "vav" and edge.downstream_role == "zone":
            vav_out[edge.upstream_iri].add(edge.downstream_iri)

    bridged: set[tuple[str, str]] = set()
    for loop_iri in set(loop_in) & set(loop_out):
        for up_iri in loop_in[loop_iri]:
            for dn_iri in loop_out[loop_iri]:
                bridged.add((up_iri, dn_iri))
    bridged_air: set[tuple[str, str]] = set()
    for vav_iri in set(vav_in) & set(vav_out):
        for up_iri in vav_in[vav_iri]:
            for dn_iri in vav_out[vav_iri]:
                bridged_air.add((up_iri, dn_iri))

    kept = [
        e
        for e in kept
        if not (
            (e.upstream_role in ("boiler", "chiller", "pump") and e.downstream_role in ("ahu", "vav") and (e.upstream_iri, e.downstream_iri) in bridged)
            or (e.upstream_role == "ahu" and e.downstream_role == "zone" and (e.upstream_iri, e.downstream_iri) in bridged_air)
        )
    ]
    kept.sort(key=lambda e: (-e.confidence, e.downstream_label, e.upstream_label))
    return kept


def load_telemetry_csv(
    path: Path,
    *,
    point_column: str = "point_key",
    timestamp_column: str = "timestamp",
    value_column: str = "value",
    site_id: str | None = None,
) -> dict[str, list[tuple[datetime, float]]]:
    """Load wide or long telemetry CSV read-only into ``point_id -> [(ts, value), ...]``."""
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames or ())
        if not cols:
            return {}
        ts_col = next(
            (c for c in (timestamp_column, "timestamp_utc", "ts", "timestamp", "time") if c in cols),
            None,
        )
        site_col = next((c for c in ("site_id", "site", "Site") if c in cols), None)

        def _row_in_site(row: dict[str, Any]) -> bool:
            if not site_id or not site_col:
                return True
            raw = (row.get(site_col) or "").strip()
            return raw.lower() == site_id.lower()
        pt_col = next(
            (c for c in (point_column, "point_key", "openfdd_key", "point_id", "point") if c in cols),
            None,
        )
        val_col = next((c for c in (value_column, "value", "val") if c in cols), None)
        if ts_col is None:
            raise ValueError(f"Telemetry CSV {path} lacks a timestamp column")

        if pt_col and val_col:
            for row in reader:
                if not _row_in_site(row):
                    continue
                ts = parse_utc(row.get(ts_col))
                pk = (row.get(pt_col) or "").strip()
                raw_v = row.get(val_col)
                if ts is None or not pk or raw_v in (None, ""):
                    continue
                try:
                    val = float(raw_v)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(val):
                    row_site = (row.get(site_col) or "").strip() if site_col else ""
                    series[_telemetry_key(row_site or site_id, pk)].append((ts, val))
            return dict(series)

        # Wide format: every non-metadata column is a point identifier
        meta_cols = {ts_col, "site_id", "site"}
        pt_cols = [c for c in cols if c not in meta_cols]
        for row in reader:
            if not _row_in_site(row):
                continue
            ts = parse_utc(row.get(ts_col))
            if ts is None:
                continue
            for pk in pt_cols:
                raw_v = row.get(pk)
                if raw_v in (None, ""):
                    continue
                try:
                    val = float(raw_v)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(val):
                    row_site = (row.get(site_col) or "").strip() if site_col else ""
                    series[_telemetry_key(row_site or site_id, pk)].append((ts, val))
    return dict(series)


def _sql_ident(name: str) -> str:
    if not isinstance(name, str) or not all(ch.isalnum() or ch in ("_", ".") for ch in name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def load_telemetry_sql(
    conn: Any,
    *,
    history_table: str = "input_sample",
    columns: Mapping[str, str] | None = None,
    site_id: str | None = None,
) -> dict[TelemetryKey, list[tuple[datetime, float]]]:
    """Read telemetry samples from a SQLite/DuckDB connection without writing anything.

    Samples are grouped by ``(site, point_key)`` whenever a site column is present,
    so unscoped loads never pool identical point keys across sites.
    """
    col_map = dict(columns or {})
    table = _sql_ident(history_table)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} WHERE 1=0")
    present = {str(d[0]).lower(): str(d[0]) for d in cur.description}

    def pick(preferred: str, fallbacks: tuple[str, ...]) -> str:
        req = col_map.get(preferred)
        if req:
            return _sql_ident(req)
        for cand in fallbacks:
            if cand.lower() in present:
                return _sql_ident(present[cand.lower()])
        raise ValueError(f"History table {history_table!r} has no {preferred} column")

    pk_col = pick("point_key", ("point_key", "openfdd_key", "point_id"))
    ts_col = pick("ts", ("ts", "timestamp", "timestamp_utc"))
    val_col = pick("value", ("value", "val"))
    site_col = col_map.get("site_id") or present.get("site_id") or present.get("site")
    site_ident = _sql_ident(site_col) if site_col else None

    if site_ident:
        sql = f"SELECT {pk_col} AS point_key, {ts_col} AS ts, {val_col} AS value, {site_ident} AS site_id FROM {table}"
    else:
        sql = f"SELECT {pk_col} AS point_key, {ts_col} AS ts, {val_col} AS value FROM {table}"
    params: list[Any] = []
    if site_id and site_ident:
        from open_fdd.rca.evidence import sql_placeholder

        sql += f" WHERE {site_ident} = {sql_placeholder(conn)}"
        params.append(site_id)
    sql += f" ORDER BY {ts_col}"

    cur.execute(sql, params)
    series: dict[TelemetryKey, list[tuple[datetime, float]]] = defaultdict(list)
    for rec in cur.fetchall():
        if site_ident:
            pk, ts_raw, val_raw, row_site = rec
        else:
            pk, ts_raw, val_raw = rec
            row_site = ""
        ts = parse_utc(ts_raw)
        if ts is None or not pk or val_raw is None:
            continue
        try:
            val = float(val_raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(val):
            row_site_s = str(row_site).strip() if row_site is not None else ""
            series[_telemetry_key(row_site_s or site_id, str(pk))].append((ts, val))
    return dict(series)


def suggested_links_to_csv(edges: Sequence[InferredEdge]) -> str:
    """Serialize proposed ``s223:connectedTo`` links as CSV for human review."""
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "upstream_id",
            "upstream_label",
            "upstream_iri",
            "predicate",
            "downstream_id",
            "downstream_label",
            "downstream_iri",
            "confidence",
            "status",
            "correlation",
            "lag_steps",
            "n_samples",
            "upstream_point",
            "downstream_point",
            "evidence",
        ]
    )
    for e in edges:
        writer.writerow(
            [
                e.upstream_id,
                e.upstream_label,
                e.upstream_iri,
                e.predicate,
                e.downstream_id,
                e.downstream_label,
                e.downstream_iri,
                f"{e.confidence:.3f}",
                "proposed_inferred_not_modeled",
                "" if e.correlation is None else f"{e.correlation:.3f}",
                "" if e.lag_steps is None else str(e.lag_steps),
                str(e.n_samples),
                e.upstream_point,
                e.downstream_point,
                "; ".join(e.evidence),
            ]
        )
    return buf.getvalue()


def suggested_links_to_ttl(edges: Sequence[InferredEdge]) -> str:
    """Serialize proposed 223P connections as an advisory Turtle file for human review."""
    lines = [
        "@prefix s223: <http://data.ashrae.org/standard223#> .",
        "",
        "# ADVISORY: Proposed s223:Connection links (inferred, not modeled).",
        "# Review and remove unwanted statements before merging into a site model.",
        "",
    ]
    for index, edge in enumerate(edges, start=1):
        ev = "; ".join(edge.evidence)
        comment = (
            f"# {edge.upstream_label} -> {edge.downstream_label} | confidence={edge.confidence:.3f} | {ev}"
        )
        comment = " ".join(comment.splitlines())
        lines.append(comment)
        conn = f"urn:openfdd:inferred:connection:{index}"
        lines.append(f"<{conn}> a s223:Connection ;")
        lines.append(f"    s223:connectsFrom <{edge.upstream_iri}> ;")
        lines.append(f"    s223:connectsTo <{edge.downstream_iri}> .")
        lines.append(f"<{edge.upstream_iri}> s223:connectedTo <{edge.downstream_iri}> .")
    return "\n".join(lines) + "\n"
