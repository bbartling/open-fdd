---
title: Engineering quantities (EQ-VOCAB)
parent: Haystack Modeling
nav_order: 14
permalink: /modeling/engineering-quantities.html
---

# Engineering quantities (EQ-VOCAB)

Open-FDD defines a **versioned** engineering-quantity vocabulary for design /
rated / TAB capacities that feed PyPI ECM tools. Telemetry and FDD math stay in
Parquet / DataFusion; these records are **model evidence**, not historian
samples.

| Field | Value |
| --- | --- |
| Vocab version | `ofdd_engineering_quantities_v1` |
| Namespace | `urn:openfdd:ns#` |
| Turtle | [vocab/ofdd_engineering_quantities_v1.ttl](vocab/ofdd_engineering_quantities_v1.ttl) |
| JSON schema | [vocab/ofdd_engineering_quantities_v1.schema.json](vocab/ofdd_engineering_quantities_v1.schema.json) |
| Python | `open_fdd.ecm_engineering.eq_vocab` (wheel copy is authoritative; Pages copy parity-tested) |

## Quantity record (required)

Each capacity property points at an `EngineeringQuantity` record with:

- `numeric_value` (finite) + registered `unit_code`
- `quantity_kind` (e.g. `ElectricalPower` vs `ThermalPower`)
- `value_basis` (`Design` \| `Rated` \| `TAB` \| `Measured` \| `Assumed`)
- `source_type` / optional locator + `review_status`

Do **not** treat thermal kW as electrical demand. Do **not** invent annual
hours or ton-hours from nameplate alone.

## Properties (v1)

`ratedCoolingCapacity`, `ratedHeatingCapacity`, `ratedFuelInputPower`,
`ratedElectricalInputPower`, `ratedShaftPower`, `designSupplyAirflow`,
`designOutdoorAirflow`, `designWaterFlow`, `designExternalStaticPressure`,
`designPumpHead`, `ratedCOP`, `ratedEER`, `ratedThermalEfficiency`.

## Related

- [RDF vocabulary notes](rdf-vocabulary.html)
- [Model → ECM calculations](../ecm/model-to-calculations.html)
- ADR: [Data model graph](../architecture/ADR_data_model_graph.html)
