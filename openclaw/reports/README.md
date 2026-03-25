# OpenClaw reports

This directory stores reusable testing reports for the Open-FDD bench.

## Purpose

Use reports to summarize runs for:
- full-stack validation
- knowledge-graph-only validation
- data-ingestion-only validation
- BACnet bench runs
- docs and parity checks

## Suggested report types

- startup report
- smoke-test report
- graph-parity report
- BACnet soak report
- regression report

## Workflow

1. Run the relevant bench mode.
2. Capture the checks performed and the result.
3. Save the summary here or in `reports/drafts/`.
4. Promote the useful bits into upstream docs later.

## Notes

Keep the reports readable and boringly repeatable. That makes them easier to upstream.
