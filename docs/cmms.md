---
title: CMMS / work-order triage
parent: Rules
nav_order: 8
---

# CMMS / work-order triage

Use a confirmed fault to suggest a work order, then have an operator review its cause and priority.
Rate the expected return from fixing it and the skill needed. The matrix below is a suggested workflow;
Open-FDD does not automatically create work orders or calculate these ratings on every FDD run.

Add **Critical** to any box when the operator identifies a safety, equipment-damage or serious comfort risk.
Follow the site's escalation procedure; a return estimate must never delay an urgent response.

## Choose a priority

| Expected return | Simple / Easy: operator | Medium / Hard / Complex: specialist |
|---|---|---|
| High or upper-medium: estimated payback within 24 months | **Fix now**: assign with clear fix notes | **Plan**: arrange engineering review and budget |
| Lower: payback beyond 24 months, or no quantified saving | **Batch**: include in a maintenance visit | **Watch**: investigate and trend; coordinate with other work |

These are starting bands, not mandatory service levels. Comfort and reliability can justify work without an energy payback.
Unknown savings mean **unquantified**, not zero; investigate important faults before assigning them a low priority.

| Skill | Typical work |
|---|---|
| Simple | Operator releases an override or corrects a schedule |
| Easy | Authorized operator adjusts a setpoint or deadband |
| Medium | Controls technician calibrates a sensor or tunes a loop |
| Hard | Controls specialist changes a sequence or integration |
| Complex | Mechanical contractor or engineer repairs or replaces equipment |

## Estimate return honestly

For an electrical runtime-waste fault, use the **avoidable incremental power**, not automatically the equipment's rated power:

```text
avoidable energy (kWh) = applicable fault hours (h) × avoidable incremental power (kW)
avoidable cost        = avoidable energy × applicable utility rate
simple payback years  = estimated fix cost / estimated annual avoidable cost
```

Use measured power where possible. Explain estimates and uncertainty. Heating fuel, demand charges and variable tariffs
need their own calculation. Do not multiply unrelated sensor fault hours by motor nameplate power.
Annualize only when the observation window represents the operating schedule and season; record the assumption.
For zero or unknown annual savings, leave payback unknown rather than dividing by zero.

Read `fault_hours` and the rule's assessed coverage together. Unassessed or missing proof is not a confirmed zero-fault result.
Overlapping rules can describe one physical problem: consolidate the work order and avoid counting the same savings twice.
See the [SQL cookbook](rules/sql-cookbook.html) for each rule's inputs, units, tuning and outputs.

## Write and verify the work order

1. Record equipment, rule, observation window, assessed coverage and the supporting trend.
2. Confirm point bindings, SI units, motor-status proof where required, and relevant tuning before diagnosing equipment.
3. Record the suspected cause, proposed skill, priority, return assumptions and any Critical escalation.
4. Assign through the site's CMMS process. Store the work-order reference with the investigation notes.
5. After the fix, rerun the rule over adequate comparable operation and review the trend. A stopped device or missing
   data does not demonstrate a successful repair.

| Example | Initial investigation / suggested routing |
|---|---|
| SCHED-247: operation outside the intended schedule | Check schedule and overrides; Fix now / Simple when waste is verified |
| SV-FLATLINE: flat sensor series | Check signal quality and actual operating conditions; Batch / Medium when noncritical |
| FC2: low mixed-air temperature | Investigate freeze exposure promptly; Critical when risk is confirmed |

Rule names identify evidence, not a guaranteed root cause. Use the [rule catalog](rules/) to find the relevant equation.
