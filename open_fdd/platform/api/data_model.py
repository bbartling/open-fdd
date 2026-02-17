"""
Data model API: export/import points (JSON for LLM), TTL from DB, run SPARQL.

Single source of truth = DB. TTL is generated from DB. CRUD mutations (delete site/equipment/point)
already update the DB; GET /data-model/ttl always reflects current state.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import (
    build_ttl_from_db,
    get_ttl_for_sparql,
    sync_ttl_to_file,
)

router = APIRouter(prefix="/data-model", tags=["data-model"])


# --- Export: points as JSON (raw names, time-series refs, optional brick_type for LLM to fill) ---


class PointExportRow(BaseModel):
    point_id: str
    site_id: str
    site_name: str | None
    external_id: str
    equipment_id: str | None
    equipment_name: str | None
    brick_type: str | None
    rule_input: str | None = Field(
        None,
        description="Name FDD rules use to reference this point's timeseries. Usually = external_id (e.g. HTG-O, CLG-O) or a short alias (e.g. htg_cmd). Maps to DB column fdd_input.",
    )
    unit: str | None


@router.get(
    "/export",
    response_model=list[PointExportRow],
    summary="Step 1: Export points for Brick mapping",
    response_description="JSON list with point_id, external_id, site_name. Use point_id when building the import body.",
)
def export_points(
    site_id: str | None = Query(
        None,
        description="Filter by site: UUID, name (e.g. BensOffice), or description. Omit for all sites.",
    ),
):
    """**Step 1 of Brick workflow.** Export all points as JSON. Use site_id = name (e.g. BensOffice) or UUID. Copy the response; add brick_type, rule_input, then PUT /data-model/import."""
    _site_id = _resolve_site_filter(site_id)
    if site_id and site_id.strip() and _site_id is None:
        raise HTTPException(404, f"No site found for name/description: {site_id!r}")
    with get_conn() as conn:
        with conn.cursor() as cur:
            if _site_id:
                cur.execute(
                    """
                    SELECT p.id, p.site_id, s.name AS site_name, p.external_id,
                           p.equipment_id, e.name AS equipment_name, p.brick_type, p.fdd_input, p.unit
                    FROM points p
                    LEFT JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    WHERE p.site_id = %s
                    ORDER BY p.external_id
                    """,
                    (str(_site_id),),
                )
            else:
                cur.execute("""
                    SELECT p.id, p.site_id, s.name AS site_name, p.external_id,
                           p.equipment_id, e.name AS equipment_name, p.brick_type, p.fdd_input, p.unit
                    FROM points p
                    LEFT JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    ORDER BY p.site_id, p.external_id
                    """)
            rows = cur.fetchall()
    return [
        PointExportRow(
            point_id=str(r["id"]),
            site_id=str(r["site_id"]),
            site_name=r.get("site_name"),
            external_id=r["external_id"],
            equipment_id=str(r["equipment_id"]) if r.get("equipment_id") else None,
            equipment_name=r.get("equipment_name"),
            brick_type=r.get("brick_type"),
            rule_input=r.get("fdd_input"),
            unit=r.get("unit"),
        )
        for r in rows
    ]


# --- Import: bulk update full BRICK data model (points, site, equipment, rule_input) ---


class PointImportRow(BaseModel):
    point_id: str = Field(
        ..., description="Point UUID from GET /data-model/export or GET /points"
    )
    site_id: str | None = Field(
        None, description="Move point to this site (UUID from GET /sites)"
    )
    equipment_id: str | None = Field(
        None, description="Assign point to this equipment (UUID from GET /equipment)"
    )
    external_id: str | None = Field(
        None, description="Rename time-series reference (e.g. HTG-O, ZoneTemp)"
    )
    brick_type: str | None = Field(
        None, description="BRICK class e.g. Supply_Air_Temperature_Sensor"
    )
    rule_input: str | None = Field(
        None,
        description="Name FDD rules use for this point. Usually = external_id (e.g. HTG-O) or alias (e.g. htg_cmd). Deprecated: fdd_input also accepted.",
    )
    fdd_input: str | None = Field(
        None, description="Deprecated. Use rule_input instead."
    )
    unit: str | None = Field(None, description="e.g. degrees-fahrenheit, percent")
    description: str | None = Field(None, description="Human-readable description")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                    "brick_type": "Supply_Air_Temperature_Sensor",
                    "rule_input": "sat",
                },
                {
                    "point_id": "b1ffcd00-0d1c-5fg9-cc7e-7cc0ce491b22",
                    "brick_type": "Zone_Air_Temperature_Sensor",
                    "rule_input": "ZoneTemp",
                },
            ]
        }
    }


class DataModelImportBody(BaseModel):
    points: list[PointImportRow]

    model_config = {
        "json_schema_extra": {
            "example": {
                "points": [
                    {
                        "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                        "brick_type": "Supply_Air_Temperature_Sensor",
                        "rule_input": "sat",
                    },
                    {
                        "point_id": "b1ffcd00-0d1c-5fg9-cc7e-7cc0ce491b22",
                        "brick_type": "Zone_Air_Temperature_Sensor",
                        "rule_input": "zt",
                    },
                ]
            }
        }
    }


@router.put(
    "/import",
    summary="Step 3: Import Brick mapping",
    response_description='Count of points updated (e.g. { "updated": 30, "total": 30 }).',
)
def import_data_model(body: DataModelImportBody):
    """**Step 3 of Brick workflow.** Full BRICK data modeling: update brick_type, rule_input (or fdd_input), site_id, equipment_id, external_id, unit, description per point. Sites created via POST /sites. Body: `{\"points\": [{\"point_id\": \"uuid\", \"brick_type\": \"...\", \"rule_input\": \"HTG-O\", \"equipment_id\": \"...\"}, ...]}`. TTL auto-syncs on import."""
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in body.points:
                updates, params = [], []
                if row.site_id is not None:
                    updates.append("site_id = %s")
                    params.append(row.site_id)
                if row.equipment_id is not None:
                    updates.append("equipment_id = %s")
                    params.append(row.equipment_id)
                if row.external_id is not None:
                    updates.append("external_id = %s")
                    params.append(row.external_id)
                if row.brick_type is not None:
                    updates.append("brick_type = %s")
                    params.append(row.brick_type)
                ri = row.rule_input if row.rule_input is not None else row.fdd_input
                if ri is not None:
                    updates.append("fdd_input = %s")
                    params.append(ri)
                if row.unit is not None:
                    updates.append("unit = %s")
                    params.append(row.unit)
                if row.description is not None:
                    updates.append("description = %s")
                    params.append(row.description)
                if not updates:
                    continue
                params.append(row.point_id)
                cur.execute(
                    f"""UPDATE points SET {", ".join(updates)} WHERE id = %s""",
                    params,
                )
                if cur.rowcount:
                    updated += 1
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {"updated": updated, "total": len(body.points)}


# --- TTL: generate from DB (always in sync with CRUD) ---


def _resolve_site_filter(site_filter: str | None) -> UUID | None:
    """Resolve site_id param: UUID, site name, or description. Returns None if empty. Omit param for all sites."""
    if not site_filter or not site_filter.strip():
        return None
    s = site_filter.strip()
    try:
        return UUID(s)
    except ValueError:
        pass
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM sites WHERE name ILIKE %s OR description ILIKE %s LIMIT 1""",
                (s, s),
            )
            row = cur.fetchone()
    return UUID(str(row["id"])) if row else None


@router.get(
    "/ttl",
    response_class=PlainTextResponse,
    summary="Step 4: View Brick TTL",
    response_description="Turtle (text/turtle) of current data model.",
)
def get_ttl(
    site_id: str | None = Query(
        None,
        description="Filter by site: UUID, site name (e.g. BensOffice), or description. Omit for all sites.",
    ),
    save: bool = Query(
        True,
        description="Write TTL to config/brick_model.ttl (default: true). Also auto-synced on every CRUD/import.",
    ),
):
    """Generate Brick TTL from current DB. Use site_id = site name (e.g. BensOffice) or description—no need for UUID. Omit for all sites."""
    _site_id = _resolve_site_filter(site_id)
    if site_id and site_id.strip() and _site_id is None:
        raise HTTPException(404, f"No site found for name/description: {site_id!r}")
    ttl = build_ttl_from_db(site_id=_site_id)
    if save:
        try:
            sync_ttl_to_file(site_id=_site_id)
        except Exception as e:
            # Still return TTL; save is best-effort (Docker may have read-only filesystem)
            resp = PlainTextResponse(ttl, media_type="text/turtle")
            resp.headers["X-TTL-Save"] = "failed"
            resp.headers["X-TTL-Save-Error"] = str(e)[:200]
            return resp
    return PlainTextResponse(ttl, media_type="text/turtle")


# --- SPARQL: run query against current TTL (from DB) ---


class SparqlRequest(BaseModel):
    query: str = Field(
        ...,
        description="SPARQL query to run against the current data model (TTL from DB).",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                "SELECT ?site ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }"
            }
        }
    }


def _run_sparql_on_ttl(ttl_content: str, query: str) -> list[dict]:
    try:
        from rdflib import Graph
    except ImportError:
        raise HTTPException(
            503,
            "rdflib required. Install: pip install open-fdd[brick]",
        ) from None
    g = Graph()
    try:
        g.parse(data=ttl_content, format="turtle")
    except Exception as e:
        raise HTTPException(400, f"Invalid TTL: {e}") from e
    try:
        results = g.query(query)
    except Exception as e:
        raise HTTPException(400, f"SPARQL error: {e}") from e
    bindings = []
    for row in results:
        bindings.append(
            {str(k): str(v) if v is not None else None for k, v in row.asdict().items()}
        )
    return bindings


@router.post(
    "/sparql",
    summary="Step 5: Run SPARQL (validate)",
    response_description="Query result bindings as JSON.",
)
def run_sparql(
    body: SparqlRequest = Body(
        ...,
        examples=[
            {
                "query": "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                "SELECT ?site ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }"
            }
        ],
    ),
):
    """Run a SPARQL query **right here in Swagger**: use the example body or paste your own query, then **Try it out** → Execute. The query runs against the current data model (TTL from DB merged with BACnet scan when present). Returns bindings as JSON. Use to validate time-series refs, BRICK mapping, no orphans. For .sparql files use POST /data-model/sparql/upload."""
    ttl = get_ttl_for_sparql()
    return {"bindings": _run_sparql_on_ttl(ttl, body.query)}


@router.post(
    "/sparql/upload",
    summary="Run a .sparql file",
    response_description="Query result bindings as JSON.",
)
async def run_sparql_upload(
    file: UploadFile = File(
        ...,
        description="Upload a .sparql file (e.g. from analyst/sparql/). Same as POST /sparql with the file contents as query.",
    ),
):
    """Upload a .sparql file to run against the current data model. Use when you have saved queries (e.g. analyst/sparql/05_site_and_counts.sparql). For ad‑hoc queries use POST /data-model/sparql and type the query in Swagger."""
    if not file.filename or not file.filename.lower().endswith(".sparql"):
        raise HTTPException(400, "Upload a .sparql file")
    query = (await file.read()).decode("utf-8")
    ttl = get_ttl_for_sparql()
    return {"bindings": _run_sparql_on_ttl(ttl, query)}
