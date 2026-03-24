# Reports

This directory is for durable overnight and review artifacts.

## Purpose

Reports here should make it easy for a human or future agent to understand:

- what the overnight process checked
- what evidence was collected
- what passed, failed, or was inconclusive
- what follow-up is needed

## Intended report types

- BACnet-to-fault verification reports
- overnight regression summaries
- docs/link review summaries
- PR review summaries when the findings are important enough to preserve

## Naming guidance

Suggested names:

- `overnight-bacnet-verification-YYYY-MM-DD.md`
- `overnight-summary-YYYY-MM-DD.md`
- `docs-link-review-YYYY-MM-DD.md`

Keep reports human-readable first. JSON sidecars can be added later if needed.
