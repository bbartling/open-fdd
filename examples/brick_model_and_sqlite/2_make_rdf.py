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
unique_sensors = set()  # To track and avoid redundancy
ahu_uris = {}  # To track and associate sensors with AHUs

# List of specific identifiers related to AHU points
ahu_related_identifiers = ["SaStaticSPt", "SaStatic", "SaFanSpeedAO"]

for timeseries_id, stored_at in timeseries_refs:
    timeseries_id = timeseries_id.strip()  # Remove any leading/trailing spaces

    # Only process the timeseries if it matches one of the AHU-related identifiers
    if any(identifier in timeseries_id for identifier in ahu_related_identifiers):
        sensor_uri = URIRef(f"http://example.org/{timeseries_id.replace(' ', '_')}")

        if timeseries_id in unique_sensors:
            continue  # Skip if this sensor has already been processed
        unique_sensors.add(timeseries_id)

        # Determine the AHU to which the sensor belongs (assuming it's part of the ID)
        ahu_name = timeseries_id.split("_")[0]  # Assuming format like 'AHU1_...'
        if ahu_name not in ahu_uris:
            ahu_uris[ahu_name] = URIRef(f"http://example.org/{ahu_name}")
            g.add((ahu_uris[ahu_name], RDF.type, brick.Air_Handling_Unit))

        # Adjust sensor type and unit based on sensor name
        if "StaticSPt" in timeseries_id:
            g.add((sensor_uri, RDF.type, brick.Supply_Air_Static_Pressure_Setpoint))
            g.add((sensor_uri, brick.hasUnit, unit.Inch_Water_Column))
            print("StaticSPt added: ", sensor_uri)
        elif "SaStatic" in timeseries_id:
            g.add((sensor_uri, RDF.type, brick.Supply_Air_Static_Pressure_Sensor))
            g.add((sensor_uri, brick.hasUnit, unit.Inch_Water_Column))
            print("SaStatic added: ", sensor_uri)
        elif "SaFanSpeedAO" in timeseries_id:
            g.add((sensor_uri, RDF.type, brick.Supply_Fan_VFD_Speed_Sensor))
            g.add((sensor_uri, brick.hasUnit, unit.Percent))
            print("SaFanSpeedAO added: ", sensor_uri)

        # Associate the sensor with the AHU
        g.add((ahu_uris[ahu_name], brick.hasPoint, sensor_uri))

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
