import sqlite3
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import RDFS, XSD

# Step 1: Set up RDF graph
g = Graph()
brick = Namespace("https://brickschema.org/schema/Brick#")
unit = Namespace("http://qudt.org/vocab/unit/")
ref = Namespace("https://brickschema.org/schema/Reference#")
g.bind("brick", brick)
g.bind("unit", unit)
g.bind("ref", ref)

# Step 2: Connect to SQLite database
conn = sqlite3.connect("brick_timeseries.db")
cursor = conn.cursor()

# Step 3: Retrieve timeseries metadata from SQLite database
cursor.execute("SELECT timeseries_id, stored_at FROM TimeseriesReference")
timeseries_refs = cursor.fetchall()

# Define the database URI
database_uri = URIRef("http://example.org/database")
g.add((database_uri, RDF.type, ref.Database))
g.add(
    (
        database_uri,
        RDFS.label,
        Literal("SQLite Timeseries Storage", datatype=XSD.string),
    )
)
g.add(
    (
        database_uri,
        URIRef("http://example.org/connstring"),
        Literal("sqlite:///brick_timeseries.db", datatype=XSD.string),
    )
)

# Step 4: Build RDF model based on the timeseries references
for timeseries_id, stored_at in timeseries_refs:
    sensor_uri = URIRef(f"http://example.org/{timeseries_id.replace(' ', '_')}")

    # Adjust sensor type and unit based on sensor name
    if "SaTempSP" in timeseries_id or "SaStatic" in timeseries_id:
        if "SPt" in timeseries_id or "SPt" in timeseries_id:  # Adjust setpoint type
            g.add((sensor_uri, RDF.type, brick.Supply_Air_Static_Pressure_Setpoint))
            g.add((sensor_uri, brick.hasUnit, unit.Inch_Water_Column))
        else:
            g.add((sensor_uri, RDF.type, brick.Supply_Air_Static_Pressure_Sensor))
            g.add((sensor_uri, brick.hasUnit, unit.Inch_Water_Column))
    elif "Sa_FanSpeed" in timeseries_id:
        g.add((sensor_uri, RDF.type, brick.Supply_Fan_VFD_Speed_Sensor))
        g.add((sensor_uri, brick.hasUnit, unit.Percent))
    else:
        # Default case (adjust as needed)
        g.add((sensor_uri, RDF.type, brick.Temperature_Sensor))
        g.add(
            (sensor_uri, brick.hasUnit, unit.DEG_F)
        )  # Assuming degrees Fahrenheit, adjust if needed

    timeseries_ref_uri = URIRef(
        f"http://example.org/timeseries_{timeseries_id.replace(' ', '_')}"
    )
    g.add((timeseries_ref_uri, RDF.type, ref.TimeseriesReference))
    g.add(
        (
            timeseries_ref_uri,
            ref.hasTimeseriesId,
            Literal(timeseries_id, datatype=XSD.string),
        )
    )
    g.add((timeseries_ref_uri, ref.storedAt, database_uri))
    g.add((sensor_uri, ref.hasExternalReference, timeseries_ref_uri))

# Step 5: Serialize the graph to Turtle format
g.serialize("brick_model_with_timeseries.ttl", format="turtle")

# Close the connection
conn.close()

print("RDF model created and saved to 'brick_model_with_timeseries.ttl'.")
