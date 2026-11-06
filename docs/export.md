---
title: Export
nav_order: 10
---

# CSV export

The **Export** tab downloads point history as one Excel-friendly CSV (UTF-8 with a byte-order mark, so `°F` and
`₂` read correctly).

1. Pick the points (the list follows the site / equipment scope selected above).
2. Pick a date-time range.
3. Pick a resolution: raw (the box's 300 s trend grid), 5 min, 15 min, 1 hour, or 1 day (UTC days).
4. Pick units: **display** (imperial or SI, as the header toggle) or **stored** (as NF holds them).
5. Click **Export CSV**.

How it works: history is resampled by NF on the box (`GET /api/v1/point/data?...&window=Ns&method=AVERAGE|MAX`),
fetched in chunks of 7 days or less and 40 points per request, and assembled in the browser. A single export is
capped at 200,000 cells; narrow the range or the point list when you hit it.

The CSV builder, range chunking, column naming and unit conversion are pure functions in
`nf-app/static/export.js`, tested in node (`nf-app/tests/export.test.mjs`).

For machine access use the NF API directly, or [SPARQL](rdf-sparql.html) for model queries.
