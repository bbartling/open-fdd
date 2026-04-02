---
title: External representations (Brick v1.4)
parent: Data modeling
nav_order: 6
---

# External representations (Brick v1.4)

Open-FDD models Brick points with Brick's **ref schema** so software can discover how each point maps to external systems (BACnet and timeseries storage) using:

- `ref:hasExternalReference`
- `ref:BACnetReference`
- `ref:TimeseriesReference`

Open-FDD keeps legacy `ofdd:*` BACnet fields for compatibility, but `ref:*` is the preferred representation.

---

## When ref triples appear in the TTL
{: #when-ref-appears-in-the-ttl }

Brick external references (`ref:hasExternalReference`, etc.) are **materialized when the Brick section of the graph is rebuilt from Postgres** and the graph is serialized (same path as `sync_brick_from_db` / TTL generation). They are **not** invented solely by BACnet discovery in memory: discovery updates **BACnet** RDF in the graph, while `ref:BACnetReference` / `ref:TimeseriesReference` under each point come from **current point rows** in the DB when that Brick sync runs.

You will see `ref:` in TTL (or in **View full data model**) after any of these:

- **CRUD or import** on sites, equipment, or points (the API reserializes Brick to disk on those paths).
- **GET /data-model/ttl** with `save=true` (default in many clients), **POST /data-model/serialize**, or **Data model → Serialize to TTL** in the UI.
- The **background graph sync** on a timer: interval **`graph_sync_interval_min`** (platform config). In the React app this is edited on **OpenFDD Config**, not the Overview page. See [Configuration → Platform keys](../configuration#platform-keys-config).

So if you only ran BACnet discovery and are watching **`config/data_model.ttl` on disk**, `ref:` may lag until the next serialize (timer or explicit action above). Discovery may also request a TTL write when **write to file** is enabled on that flow—otherwise rely on CRUD/import or an explicit serialize.

---

## What Open-FDD emits

For each point in `config/data_model.ttl`:

- A **timeseries reference**:
  - `a ref:TimeseriesReference`
  - `ref:hasTimeseriesId "<external_id>"`
  - `ref:storedAt "<postgresql://host:port/db/timeseries_readings>"`

- A **BACnet reference** when BACnet addressing is known (`bacnet_device_id` + `object_identifier`):
  - `a ref:BACnetReference`
  - `bacnet:object-identifier "<object-type,instance>"`
  - optional `bacnet:object-name "<name>"`
  - `bacnet:objectOf <bacnet://<device_instance>>`
  - `brick:BACnetURI "bacnet://<device>/<object>/present-value"`

---

## Example

```turtle
:pt_123 a brick:Zone_Air_Temperature_Sensor ;
    rdfs:label "ZoneTemp" ;
    ref:hasExternalReference [
        a ref:BACnetReference ;
        bacnet:object-identifier "analog-input,3" ;
        bacnet:object-name "BLDG-Z410-ZATS" ;
        brick:BACnetURI "bacnet://123/analog-input,3/present-value" ;
        bacnet:objectOf <bacnet://123>
    ] ;
    ref:hasExternalReference [
        a ref:TimeseriesReference ;
        ref:hasTimeseriesId "ZoneTemp" ;
        ref:storedAt "postgresql://localhost:5432/openfdd/timeseries_readings"
    ] ;
    brick:isPointOf :eq_ahu_1 .
```

---

## SPARQL discovery pattern

Use this to enumerate all external references and their types:

```sparql
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT ?point ?rep ?type WHERE {
  ?point ref:hasExternalReference ?rep .
  ?rep a ?type .
}
```

BACnet-only references:

```sparql
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?point ?oid ?dev WHERE {
  ?point ref:hasExternalReference ?rep .
  ?rep a ref:BACnetReference ;
       bacnet:object-identifier ?oid ;
       bacnet:objectOf ?dev .
}
```

Timeseries-only references:

```sparql
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT ?point ?tsid ?store WHERE {
  ?point ref:hasExternalReference ?rep .
  ?rep a ref:TimeseriesReference ;
       ref:hasTimeseriesId ?tsid ;
       ref:storedAt ?store .
}
```

