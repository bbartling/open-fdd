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
from open_fdd.platform.data_model_ttl import build_ttl_from_db

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
    fdd_input: str | None
    unit: str | None


@router.get(
    "/export",
    response_model=list[PointExportRow],
    summary="Export points as JSON",
    response_description="List of points with time-series refs (point_id, site_id) and raw names (external_id). Add brick_type/fdd_input via PUT /import.",
)
def export_points(
    site_id: UUID | None = Query(
        None,
        description="Filter by site UUID. Omit to export all sites.",
        examples=["a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"],
    ),
):
    """Export points as JSON: raw point names (external_id), time-series refs (point_id, site_id), and optional brick_type/fdd_input. Use for LLM to add best-fit BRICK then PUT /data-model/import. **Try it out:** leave site_id empty to get all points, or paste a site UUID from GET /sites."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if site_id:
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
                    (str(site_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT p.id, p.site_id, s.name AS site_name, p.external_id,
                           p.equipment_id, e.name AS equipment_name, p.brick_type, p.fdd_input, p.unit
                    FROM points p
                    LEFT JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    ORDER BY p.site_id, p.external_id
                    """
                )
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
            fdd_input=r.get("fdd_input"),
            unit=r.get("unit"),
        )
        for r in rows
    ]


# --- Import: bulk update brick_type / fdd_input from LLM-enriched JSON ---


class PointImportRow(BaseModel):
    point_id: str = Field(..., description="Point UUID from GET /data-model/export")
    brick_type: str | None = Field(None, description="BRICK class e.g. Supply_Air_Temperature_Sensor")
    fdd_input: str | None = Field(None, description="Rule input name e.g. sat")


class DataModelImportBody(BaseModel):
    points: list[PointImportRow]

    model_config = {
        "json_schema_extra": {
            "example": {
                "points": [
                    {
                        "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                        "brick_type": "Supply_Air_Temperature_Sensor",
                        "fdd_input": "sat",
                    },
                    {
                        "point_id": "b1ffcd00-0d1c-5fg9-cc7e-7cc0ce491b22",
                        "brick_type": "Zone_Temperature_Sensor",
                        "fdd_input": "zt",
                    },
                ]
            }
        }
    }


@router.put(
    "/import",
    summary="Bulk update BRICK mapping",
    response_description="Count of points updated.",
)
def import_data_model(body: DataModelImportBody):
    """Bulk update points with brick_type and/or fdd_input (e.g. from LLM-enriched export). Use point_id from GET /data-model/export. DB is source of truth; next GET /data-model/ttl will reflect these. **Try it out:** use the example body and replace point_id with real UUIDs from your export."""
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in body.points:
                updates, params = [], []
                if row.brick_type is not None:
                    updates.append("brick_type = %s")
                    params.append(row.brick_type)
                if row.fdd_input is not None:
                    updates.append("fdd_input = %s")
                    params.append(row.fdd_input)
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
    return {"updated": updated, "total": len(body.points)}


# --- TTL: generate from DB (always in sync with CRUD) ---


@router.get(
    "/ttl",
    response_class=PlainTextResponse,
    summary="Generate Brick TTL from DB",
    response_description="Turtle (text/turtle) of current data model.",
)
def get_ttl(
    site_id: UUID | None = Query(
        None,
        description="Only include this site. Omit for all sites.",
    ),
    save: bool = Query(
        False,
        description="If true, write TTL to config/brick_model.ttl on server.",
    ),
):
    """Generate Brick TTL from current DB. Always reflects current sites/equipment/points. **Try it out:** leave params default to get full model as Turtle."""
    ttl = build_ttl_from_db(site_id=site_id)
    if save:
        path = Path("config/brick_model.ttl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ttl, encoding="utf-8")
        return PlainTextResponse(ttl, media_type="text/turtle")
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
        bindings.append({str(k): str(v) if v is not None else None for k, v in row.asdict().items()})
    return bindings


@router.post(
    "/sparql",
    summary="Run SPARQL in Swagger",
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
    """Run a SPARQL query **right here in Swagger**: use the example body or paste your own query, then **Try it out** → Execute. The query runs against the current data model (TTL generated from DB). Returns bindings as JSON. Use to validate time-series refs, BRICK mapping, no orphans. For .sparql files use POST /data-model/sparql/upload."""
    ttl = build_ttl_from_db()
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
    ttl = build_ttl_from_db()
    return {"bindings": _run_sparql_on_ttl(ttl, query)}
