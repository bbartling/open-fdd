---
title: Export
nav_order: 13
---

# CSV export

The Export tab downloads selected point history as CSV. Choose points, a date range, a resolution, and either display
units or stored units. The output is UTF-8 with a byte-order mark for spreadsheet compatibility.

Resolutions include the raw trend interval and coarser buckets. NF performs the resampling. Long ranges are fetched
in bounded time and point chunks, then assembled in the browser. Export has a cell limit. Reduce the range or point
selection if it is exceeded. Range controls follow the site's timezone. See [Charts](charts.html).

For automation, use the NF point-data API described in the [API reference](fdd-data-access.html). The CSV builder,
unit conversion, and chunk handling live in nf-app/static/export.js.
