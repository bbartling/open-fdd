# Open-FDD point roles

One point-role vocabulary for Open-FDD, open-hvac-edge and nf-hvac-functional-test. Each role is an ASHRAE 223P
property pattern with a QUDT unit and one Haystack 4 binding. The three apps are intended to adopt this file after
their migrations. None keeps its own role table.

| File | What |
|---|---|
| `openfdd-roles.json` | The vocabulary: sources, lexicon, derivation rule, units, Haystack binding rules, 89 roles |
| `openfdd-roles.schema.json` | JSON Schema (2020-12) for the file |
| `validate_roles.py` | Checks schema, name derivation, units, binding safety and NF classes; `--ontology-dir` also checks every term against the pinned ontologies |
| `test_validate_roles.py` | Tests for the validator: the real file passes, and each kind of mutation is flagged |
| `issues/` | Migration issues for the three apps |

Status: `1.1.0-draft.1`, targeted at Open-FDD 5.0.22. 89 roles: 72 are pure 223P and 17 are extensions.

## A role entry

| Field | Meaning |
|---|---|
| `role` | snake_case name, derived from `s223` (below) |
| `grounding` | `s223`, or `extension` when any basis term is `ext:*` |
| `s223` | `property_class` (Quantifiable/Enumerated, Observable/Actuatable) plus medium, roles, aspects, quantity kind or enumeration kind, equipment, connection point, and `applies_to` (the equipment classes that carry the pattern) |
| `unit`, `value_type`, `range` | QUDT unit (`null` for enumerated properties), `number`/`boolean`/`enumeration`, and the valid range |
| `writable` | `never` or `model`; a ceiling, never a grant |
| `haystack` | `kind`, `unit` symbol, NF `classes`, required `markers`, `optional`, `forbid`, `custom_markers`, `alt_markers`, `equip_markers`, `binding_scope`, `conformance` |
| `consumers` | which app reads or writes the role |
| `legacy_keys`, `aliases` | old Open-FDD keys and names used by the other vocabularies; migration only |

## Derivation rule

The name is computed from the 223P basis. Nobody chooses it.

```
role = '_'.join(tokens)
tokens = lexicon tokens of the basis, in slot order:
  scope, equipment_role, equipment_medium, equipment, roles, connection_point (only when roles is empty),
  medium, constituent, qualifier, quantity_kind, enumeration_kind, aspects (in aspect_order)
then the suffix from the property class:
  QuantifiableObservableProperty   ""
  QuantifiableActuatableProperty   "command"  ("" when the aspect is Setpoint, Maximum or Minimum)
  EnumeratedObservableProperty     "status"
  EnumeratedActuatableProperty     "command"
drop empty tokens; drop a token whose words all occur in the token kept just before it
```

Examples:

| Basis | Name |
|---|---|
| QOP, Role-Discharge, Fluid-Air, Temperature | `discharge_air_temperature` |
| QAP, Role-Discharge, Fluid-Air, Temperature, Aspect-Setpoint | `discharge_air_temperature_setpoint` |
| QAP, Role-OutdoorAirIntake Damper, DimensionlessRatio, Binary-Position | `outdoor_air_intake_damper_position_command` |
| QOP, same | `outdoor_air_intake_damper_position` |
| EOP, Role-Supply Fan, Binary-OnOff, Aspect-OperatingStatus | `supply_fan_operating_status` |

So `_command` and `_status` are not hand-picked: they come from the 223P property class. A position role bound to a
`cmd` point is a contract error. Every term maps to exactly one token in `lexicon`. Four terms map to an empty token,
each with a reason: `Electricity-AC`, `DimensionlessRatio`, `Binary-OnOff` and `Binary-Logical`.

## Extensions

A term with no 223P basis is written `ext:Name`. Its lexicon entry carries `extension: true`, `closest` (the nearest
223P term) and `why`. There are 11 such terms: Mixed, Preheat, WeatherService, Speed, ResetRequest,
StaticPressureResetRequest, LoadSatisfied, Total, Mode-Test, Mode-MaximumCooling and Mode-Purge. A role that uses one
is `grounding: extension`. New vocabulary is never added silently: add an `ext:` term with its justification, or use a
published 223P term.

## Units

On the wire, a value is in its role's QUDT unit, and the unit token is the QUDT local name (`DEG_C`, `PA`,
`L-PER-SEC`, `PERCENT`, `PERCENT_RH`, `PPM`, `KiloW`, `KiloW-HR`, `A`, `NUM`). The Haystack symbol (`°C`, `Pa`,
`L/s`, `%`, ...) is for display and tagging.

**Ratios use `unit:PERCENT` (0-100).** The open223 example models use PERCENT for DimensionlessRatio 453 times and
UNITLESS 108 times, and the Guideline 36 example models use PERCENT for every DimensionlessRatio, including all 27
damper and valve positions. The edge and functional-test apps already use percent. Relative humidity uses `PERCENT_RH`, and CO2 uses `PPM`.

`ingest_conversions` lists the only conversions allowed at ingest (`si = value * multiplier + offset`), including
`fraction` (0-1) to percent (x100). Rules and thresholds never convert.

## Haystack binding

`haystack.binding_rules` in the JSON is normative. In short:

- NF exposes `class` and `markers` (one comma-separated string). Split `markers` on commas and trim each marker.
- A point binds a role by NF class, or by carrying all `markers` (or one `alt_markers` set) plus every
  `custom_markers` entry. In both cases it carries no `forbid` marker.
- A point carries exactly one of `sensor`, `sp` or `cmd`, and the role's class sets which one: setpoints and limits
  use `sp`, actuatable properties use `cmd`, observable properties use `sensor`.
- Setpoints forbid `max` and `min`. A maximum forbids `min`, and a minimum forbids `max`.
- `equip_markers` are matched on the parent equipment. `equip_forbid` are markers the parent must not carry.
  `binding_scope` says whose point is meant (own, the air handler that feeds it, an aggregate, weather, or derived).
  A shared NF class is a collision when those parent constraints can both hold.
- If a point still matches more than one role, a strict superset of markers wins. Any remaining tie leaves the point
  unbound, and the app reports it.
- `conformance`: `standard` uses Haystack 4 markers in a standard combination, `nonstandard` uses Haystack 4 markers in
  a combination the standard does not define (coil air temperatures), and `custom` needs a marker from
  `haystack.custom_markers` (smoke, test, mode, request, satisfied, preheat). Haystack 4 has no `supply`, `ductStatic`,
  `smoke` or `test` marker.

## Writes

Writable roles: the four damper and valve position commands, the airflow setpoint, and the test, maximum-cooling and
purge mode commands. A consumer writes a point only when the role says `model`, the site model marks the point
writable, and the consumer's own runtime checks pass. Limits (`*_maximum`, `*_minimum`) and observable properties are
never written. The validator fails if a point that matches a different role could also match a writable role.

## Consuming the file

1. Pin it. Vendor `openfdd-roles.json` at a released Open-FDD tag into your repo, and record the tag and its sha256
   next to it. Starting with 5.0.22 the Open-FDD rules bundle carries the file and its sha256 in its manifest; vendor
   it from there. Never fetch it at runtime.
2. Use `role` everywhere: storage, APIs, configs and UI. Use `legacy_keys` and `aliases` only to migrate stored data
   and old configs. Resolve the names in `ambiguous_legacy_names` by the point's function marker; never alias them to a
   single role.
3. Take units, ranges, writability and tag sets from the file. Do not copy them into code.

Versioning: renaming or removing a role, or changing a unit or binding, is a major bump. Adding a role is a minor bump.
Wording changes are a patch.

## Validation

```bash
python3 roles/validate_roles.py
python3 -m unittest roles/test_validate_roles.py -v
```

Deep check: download the files named in `sources` into one directory under their `file` names (for QUDT, extract
`archive_path` from the 3.4.0 release zip). Then run:

```bash
python3 -m pip install rdflib jsonschema
python3 roles/validate_roles.py --ontology-dir DIR
ROLES_ONTOLOGY_DIR=DIR python3 -m unittest roles/test_validate_roles.py
```

The deep check verifies sha256 pins, that every `s223:`, `quantitykind:` and `unit:` term exists, that units carry the
claimed quantity kinds, that the broader chains match QUDT, that every Haystack marker is a Haystack 4 def (and every
custom marker is not), and that every Haystack unit symbol is in `units.txt`.

## Parity test recipe (each consumer)

Add one CI test that fails on drift:

1. The vendored file's sha256 equals the recorded pin.
2. Every role id your code uses (role tables, configs, SQL aliases, API enums, fixtures) is a `role` in the file.
   Grep for retired names (`legacy_keys`, `aliases`) and fail on any hit outside migration code.
3. For every role you use, your unit equals `unit` (or `units[unit].haystack` where you show symbols), and your range
   and writability are no looser than the file's.
4. Your Haystack matcher, run against the file's own tag sets, reproduces `markers`, `forbid`, `custom_markers`,
   `equip_markers` and `equip_forbid` for every role. A point carrying the markers of role B never binds a writable role A.

Example in Python:

```python
import hashlib, json, pathlib
raw = pathlib.Path("vendor/openfdd-roles.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == pathlib.Path("vendor/openfdd-roles.sha256").read_text().split()[0]
roles = {r["role"]: r for r in json.loads(raw)["roles"]}
for name, unit in MY_ROLE_UNITS.items():
    assert name in roles, name
    assert unit == roles[name]["unit"], name
```
