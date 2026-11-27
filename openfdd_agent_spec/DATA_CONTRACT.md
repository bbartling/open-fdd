# Data contract (5.0)

## Units: SI inside, display on top

FDD and analytics math run in **SI only**. Ingest converts (`ofddUnits.toSI(value, unit)`), the UI displays
(`fromSI`, `deltaFromSI`, toggle stored in `localStorage["openfdd-units"]`, default imperial). Thresholds are SI and
the unit is shown. Imperial is display-only. Source of truth for display conversion: `nf-app/static/units.js`.

| Quantity | SI unit | Imperial display | Some accepted ingest units |
|---|---|---|---|
| temperature | °C | °F | °F, K |
| pressure | Pa | inH₂O | kPa, inH2O, psi, bar |
| flow | L/s | cfm | m³/s, m³/h, cfm, gpm |
| power | kW | kW | W, MW, Btu/h, ton, hp |
| energy | kWh | kWh | Wh, MWh, kBtu, MMBtu, therm |
| percent | % (0-100) | % | %RH, pct |
| concentration | ppm | ppm | |

Temperature differences use `deltaFromSI` (no 32-degree offset). An unknown unit is not converted: the hook logs it and
skips rules that need it; fix the `unit` tag in NF. Never convert inside a rule.

## Result points (written by the `fdd` hook)

One point per (equip, rule), uuid derived deterministically from the app id and name. Two records: an `automation`-layer
record (`application_id=open-fdd`, `type=fdd-result`) holding the history, and a `model`-layer record with tags:

| Tag | Value |
|---|---|
| `markers` | `point,his,fault,fdd` for fault rules; `point,his,metric,fdd` for metric rules |
| `ruleRef` | the rule id (for example `AHU-SATDEV`) |
| `equipRef`, `siteRef` | the equip and site the result belongs to |
| `unit`, `dis`, `kind` | unit of the value, display name, `Number` |

Value: fault % of covered time over the window (fault rules) or the rule's first output column (metric rules).

## Roles (223P) and units on the wire

Canonical file: `roles/openfdd-roles.json`, version `1.0.0-draft.1` (`roles/README.md`). A role name is derived from an
ASHRAE 223P property pattern. Haystack 4 is the binding overlay only (NF `class` and markers). Do not invent role names.

On the wire the unit token is the QUDT local name (`unit:DEG_C`, `unit:PA`, `unit:L-PER-SEC`, `unit:PERCENT`,
`unit:PERCENT_RH`, `unit:PPM`, `unit:KiloW`, `unit:KiloW-HR`, `unit:A`, `unit:NUM`). The Haystack symbol (`°C`, `Pa`,
`L/s`, `%`) is display and tagging. The UI API
contract is `openapi/open-fdd-ui-api.yaml` version `1.0.0`.

The SQL catalog still keys rules with legacy role ids (`sat`, `fan_cmd`). `legacy_keys` on each role is the migration
map. New SQL uses a key that `nf-app/static/fdd-catalog.json` already lists. Roles whose `sql/fdd/input_contract.json`
scale is `fraction` are 0–1 in the scratch tables. Do not convert them again inside a rule.

Issue #1740 (feeds topology, extra zone and pump roles) is not in this tree. Do not add `fdd.feeds` or those roles here.

## Results, run proof, sensor sweeps

`fault_pct` is `fault_hours / active_hours` on a run-proof gated rule, and `fault_hours / covered_hours` otherwise.
`active_hours` is proven-on time, a rule output. On Timescale it is stored in `fdd.rule_result.metrics`, not as its own
column. Status values: `PASS`, `FAULT`, `INCONCLUSIVE`, `SKIPPED`, `ERROR`, `STALE`, `METRIC`.

Missing run proof is `SKIPPED` with reason `no_run_proof`. That is unknown, never off, and never a stored zero. A proof
that is bound and off is assessed.

`SV-STALE` is missing data only. A value that is stuck but still polled is `SV-FLATLINE`. `SV-RANGE`, `SV-SPIKE`,
`SV-FLATLINE`, `SV-STALE` and `SV-RATE` each return one row per sensor (`series_id` / `subject_key`).

One user-facing timer per rule: `confirm_min`, or the single window length (`flatline_hours`, `sustain_hours`,
`fixed_flow_hours`, `window_hours`, `stale_after_hours`). Other delays are `internal_constants`, not tuners.

Saved site and equipment tuning must keep applying. Renaming or retiring a rule id needs a tested migration of saved
overrides. `nf-app/static/rule-tuning.js` migrates parameter aliases and retired keys. It does not move a saved config
onto a new rule id. Shipped defaults are SI starters. Guideline 36 figures are cited in `docs/rules/defaults-g36.md`.
They are not the defaults unless the registry says so.

## Role binding

Rules and charts need **roles**. The canonical name is the 223P role above. `nf-app/static/fdd-catalog.json` (generated)
lists each legacy role key's NF classes and Haystack markers. `fdd.js` binds a point to a role when:

1. its NF `class` is in the role's class list (best match), else
2. it carries every marker of the role.

Weather-service points (marker `weather`) fill only `web_*` roles; equipment sensors never do. Equipment kinds come
from the equip's own markers.

Hard rules (GitHub #1537, #1538; tests in `nf-app/tests/binding-issues.test.mjs`):

- **No name, suffix or key-syntax inference.** A point named like a setpoint is not a setpoint; opaque uuids and names are never parsed.
- **Site-scoped equips.** Equip ids are only unique within a site: a point belongs to an equip only when both `equipRef`
  and `siteRef` match. Never bind across sites.
- Equipment membership comes only from the point's current `equipRef` and `siteRef`.
