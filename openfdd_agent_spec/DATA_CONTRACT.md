# Data contract (5.0)

## Units: SI inside, display on top

FDD and analytics math run in **SI only**. Ingest converts (`ofddUnits.toSI(value, unit)`), the UI displays
(`fromSI`, `deltaFromSI`, toggle stored in `localStorage["openfdd-units"]`, default imperial). Rules and thresholds are SI.
Source of truth: `nf-app/static/units.js`.

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

## Role binding

Rules and charts need **roles** (for example `sat`, `zone_t`). `nf-app/static/fdd-catalog.json` (generated) lists each
role's NF classes and Haystack markers. `fdd.js` binds a point to a role when:

1. its NF `class` is in the role's class list (best match), else
2. it carries every marker of the role.

Weather-service points (marker `weather`) fill only `web_*` roles; equipment sensors never do. Equipment kinds come
from the equip's own markers.

Hard rules (GitHub #1537, #1538; tests in `nf-app/tests/binding-issues.test.mjs`):

- **No name, suffix or key-syntax inference.** A point named like a setpoint is not a setpoint; opaque uuids and names are never parsed.
- **Site-scoped equips.** Equip ids are only unique within a site: a point belongs to an equip only when both `equipRef`
  and `siteRef` match. Never bind across sites.
- Equipment membership comes only from the point's current `equipRef` and `siteRef`.
