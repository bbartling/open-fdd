# Haystack Assignment Model

Everything that needs to be AI-drivable is assigned through Haystack IDs.

## Rule

Do not bind algorithms or fault equations directly to BACnet, Modbus, JSON API, or a Haystack remote source.

Bind this way:

```text
driver point / external ref
→ Haystack point ID
→ Arrow storage ref
→ DataFusion SQL fault equation
→ CDL algorithm input/output
```

## Why

This makes algorithms protocol agnostic:

```text
BACnet point
Modbus register
JSON API field
Haystack remote ref
```

can all satisfy the same algorithm input as long as they map to the same Haystack point ID.

## API

```text
GET  /api/model/assignments
POST /api/model/assignments/save
POST /api/model/assignments/resolve
GET  /api/model/algorithm-bindings
GET  /api/control/cdl/bindings
POST /api/control/cdl/bindings/save
```

## Example

```json
{
  "haystack_id": "point:sat",
  "driver_bindings": [
    {"driver": "bacnet", "ref": "bacnet:1001:analog-input:1"}
  ],
  "storage_ref": "arrow://hvac/sat",
  "external_refs": [
    {"system": "niagara-haystack", "ref": "@ahu1-sat"}
  ]
}
```

## CDL

CDL algorithms bind to Haystack refs:

```json
{
  "algorithm_id": "g36_ahu_vav_trim_respond",
  "inputs": {
    "duct_static": "point:duct-static",
    "sat": "point:sat"
  },
  "outputs": {
    "duct_static_sp": "point:duct-static-sp",
    "sat_sp": "point:sat-sp"
  }
}
```

The selected driver for each Haystack point can be BACnet, Modbus, JSON API, or Haystack.
