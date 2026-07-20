# Mechanical-Cooling Proof and Complete WattLab Export Design

## Goal
Make mechanical-cooling runtime evidence explicit and user-selectable while ensuring every WattLab dump contains a complete cookbook evaluation.

## Approved behavior

### Runtime proof mode
The sidebar adds `Use mapped mechanical-cooling status proof`, default `true`.

- Checked: CHW plants use hard proof in this order: mapped pump status/command, chiller/compressor status, amps above 5 A, power above 1 kW.
- Unchecked: CHW plants use valid leaving-water temperature (`32°F < CHW supply < CHW leave proof max °F`). This is labeled `inferred: chw_leave_temp` because cold water can pass through an idle chiller.
- AHU/HP DX devices continue to require compressor/DX proof in either mode; the temperature override is specific to CHW plants.
- The threshold slider is disabled while hard-status mode is checked.
- The mode is saved/restored through `session_config.json` and propagated through the headless agent API.

### Overview transparency
Overview always displays a non-collapsed mechanical-cooling device table for every cooling-capable CHW plant/AHU/HP candidate. Columns include device name, included/excluded state, selected proof, inferred/runtime hours, checked roles, and reason/warning. Excluded devices remain visible even though they have no chart bins. `ALL` remains summed device-hours, not unique plant elapsed hours.

### Complete WattLab dump
`Build WattLab dump (zip)` always executes the complete active cookbook for all loaded equipment immediately before export. It does not reuse potentially partial `batch_results`. The new complete result set replaces session `batch_results`, and the dump records all results, settings, analytics, and manifest entries.

## Safety and honesty
Temperature inference is never automatic and never silently mixed with hard proof. The UI warns that water temperature is indirect evidence. No CHW valve position is accepted as compressor proof. Existing strict behavior remains the default.

## Tests
- Unit tests cover strict order, explicit temperature mode, threshold effect, inferred labels, complete coverage rows, and device-hour aggregation.
- Session/config and AppTest coverage validate checkbox default, slider disabled/enabled state, and Overview visibility.
- Export regression test proves an existing partial session cannot produce a partial WattLab dump.
- Existing analytics, package, turnkey, and agent API suites must remain green.
