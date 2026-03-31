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

