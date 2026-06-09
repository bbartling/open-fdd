---
title: Standards crosswalk
parent: Fault Codes
nav_order: 2
---

# Standards crosswalk

Grade-A fault definitions carry a `standards_crosswalk` block in `open_fdd/faults/catalog/*.yaml`.

| Field | Source | Use in Open-FDD |
|-------|--------|-----------------|
| `ornl_lbnl_taxonomy` | ORNL/LBNL unified HVAC fault taxonomy | Canonical ontology backbone |
| `ashrae_g36_reference_type` | ASHRAE Guideline 36 | Trim-and-respond, plant requests, supervisory sequences |
| `ashrae_207_reference_type` | ASHRAE Standard 207 | Economizer FDD test categories |
| `brick_classes` | [Brick Schema](https://brickschema.org/) | Equipment/point semantic roles |
| `haystack_tags` | Project Haystack (optional) | Interoperability tags |

## Example

```yaml
standards_crosswalk:
  ornl_lbnl_taxonomy: ahu/economizer/free_cooling
  ashrae_g36_reference_type: supply_air_temp_reset
  ashrae_207_reference_type: economizer_fault_detection
  brick_classes: [brick:Air_Handler_Unit, brick:Economizer]
  haystack_tags: [equip, ahu, econ]
```

Export full catalog: `python3 -c "from open_fdd.faults.catalog import catalog_export; import json; print(json.dumps(catalog_export(), indent=2))"`
