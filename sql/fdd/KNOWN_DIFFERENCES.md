# Known differences and release blockers

## SV-RATE: equal hours, different fault timestamps

The independently authored raw fault window is 2026-01-07T11:05:00Z through 12:05:00Z, end exclusive: 12 samples, exactly 3,600 seconds. The real Open-FDD pandas oracle returns that window. Both SQL versions return 11:00:00Z through 12:00:00Z: also 12 samples and one hour, but two timestamps disagree.

This is not rounding noise. The source SQL checks two consecutive instantaneous exceedances. The pandas implementation uses a rolling median of instantaneous rates with a 15-minute horizon, fallback window rates, profile-specific thresholds, noise deadband, persistence, extreme-event handling and operating-state context. The portable SQL currently represents only a subset. `persistence_min` is advertised in the SQL registry but is not consumed by its template.

The strict suite deliberately fails SV-RATE for immediate and 15-minute confirmation, in both dialects. It has no xfail or relaxed tolerance. To close the blocker, port the actual profile algorithm and tuning effects to the target warehouse, or explicitly version the portable screening rule as a different algorithm. Do not change the expected timestamps to fit whichever output is convenient. With profile-equivalent behavior, retain the authored golden and add noise/transition/profile boundary fixtures. A source-faithful portable subset can remain separately documented, but cannot claim full Open-FDD pandas parity.

## Imported FC1 healthy baseline was not healthy under current rules

The old fixture held duct static at 1.2 against a 1.5 setpoint during ordinary fan-on hours. Current pandas/SQL use fan status for full-fan proof and therefore detect roughly 40 hours rather than the old one-hour expectation. The new fixture explicitly sets static equal to its setpoint outside the intended injection while preserving the one-hour injection and golden interval. This is a new fixture correction, not a changed expected value. The original ZIP remains byte-for-byte intact. `reports/initial_import_comparison.json` retains the original failure evidence.

## Default startup/mode behavior is not yet fully equivalent

Some SQL rules check fan-on stability, while pandas GL36 rules suppress faults after heat/cool/economizer mode changes. The raw synthetic contract explicitly sets `mode_delay_min=0` and `startup_delay_min=0` where exposed; confirmation is tested separately. Source UI/default tuner values are retained unchanged. Passing these controlled cases does not establish full default-mode or arbitrary-tuning parity. Implement and test the selected holdoff policy before shipping those controls as equivalent.

## Oracle versions

The preparation host's installed `open-fdd` distribution is 4.4.1 (62 diagnostic rules). The copied local source snapshot declares 4.4.9 (71 rules). The installed-mode report has nine `ORACLE_UNAVAILABLE` entries for FCU rules, plus the SV-RATE failure. An absent oracle is never counted as pass. The source snapshot is explicitly selected; it is not represented as a downloaded/installed 4.4.9 release. Pin the actual published package available in your environment and rerun that mode.

## Other caveats

- Actual PostgreSQL and other warehouse engines were not available here; offline DuckDB execution does not qualify those engines.
- The six analytic/utility cases use authored numerical expectations; they are not diagnostic `open_fdd.rules.run_rule` twins.
- Three aggregate-only FCU rules do not implement configurable confirmation. The tests keep their confirmation at zero and the UI must label/disable unsupported controls.
- Utility fault-hours retain a fixed 720-hour proxy. This is not measured fault duration, including in the interval-MAE rule.
- The suite has a healthy background for each positive case but does not yet prove every threshold, tuner, input gap, irregular interval or site-isolation branch. The passing contract tests prove the harness/unit/duration machinery and representative tuning effects.
- Sensor-sweep tolerance metadata may span different physical quantities. Temperature display conversions are a convenience, not permission to apply Celsius offsets to humidity or pressure tolerances. Resolve per-role quantities explicitly for a warehouse UI.
