// The shared-shell checks (top bar, equip pickers, heat-map dropdown, Other signals, Weather category, weather mirror)
// live in nf-app/tests/shell.test.mjs and run against both editions; this file makes `node --test lite/tests` run them too.
await import("../../nf-app/tests/shell.test.mjs");
