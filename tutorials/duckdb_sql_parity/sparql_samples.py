"""SPARQL finds Haystack-derived points; DuckDB summarizes their SI history."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from rdflib import Graph, Literal, Namespace, RDF
from open_fdd.parity import generate


def main() -> None:
    ds = generate(seed=0, equips=2, days=3, profile="basic")
    points, samples = ds.to_core_rows()

    # Avoid writing databases or changing any checked-out application files.
    points_df = pd.DataFrame(points)
    sample_df = pd.DataFrame(
        samples, columns=["site_id", "point_key", "ts_ms", "value"]
    )
    ex = Namespace("urn:openfdd:")
    graph = Graph()
    for point in points:
        if point.get("series"):
            continue
        if not all(point.get(field) is not None
                   for field in ("point_key", "equipment_id", "role")):
            continue
        node = ex[str(point["point_key"]).replace("/", "_")]
        graph.add((node, RDF.type, ex.Point))
        graph.add((node, ex.equipment, Literal(str(point["equipment_id"]))))
        graph.add((node, ex.role, Literal(str(point["role"]))))
        graph.add((node, ex.pointKey, Literal(str(point["point_key"]))))

    query = """
        PREFIX ex: <urn:openfdd:>
        SELECT ?equip ?key WHERE {
            ?point a ex:Point ;
                   ex:equipment ?equip ;
                   ex:role ?role ;
                   ex:pointKey ?key .
            FILTER(?role IN ("sat", "duct_static"))
        } ORDER BY ?equip ?key
    """
    selected = [(str(row.equip), str(row.key)) for row in graph.query(query)]
    if not selected:
        raise SystemExit("No SAT or duct static points matched the model.")

    with duckdb.connect(":memory:") as conn:
        conn.execute("SET TimeZone = 'UTC'")
        conn.register("points_dataframe", points_df)
        conn.register("samples_dataframe", sample_df)
        conn.execute("CREATE TABLE point AS SELECT * FROM points_dataframe")
        conn.execute("""
            CREATE TABLE input_sample AS
            SELECT site_id, point_key,
                   to_timestamp(ts_ms / 1000.0) AS ts, value
            FROM samples_dataframe
        """)
        keys = sorted({key for _, key in selected})
        rows = conn.execute("""
            SELECT point_key, count(*) AS n,
                   round(min(value), 2) AS min_si,
                   round(max(value), 2) AS max_si
            FROM input_sample
            WHERE point_key = ANY(?)
            GROUP BY point_key ORDER BY point_key
        """, [keys]).fetchall()
    if not rows:
        raise SystemExit("SPARQL keys did not match DuckDB sample records.")
    print(f"SPARQL selected {len(selected)} equipment-point bindings.")
    print("point_key | samples | min SI | max SI")
    for row in rows:
        print(*row, sep=" | ")


if __name__ == "__main__":
    main()
