# Sandbox: very rough simultaneous heat / cool penalty

**Intent:** Show how **engineering capacity on the graph** (from Data Model Engineering → `ofdd:coolingCapacityTons`, `ofdd:heatingCapacityMBH`) plus **time-series** (valve %, SAT, etc.) can feed a **back-of-envelope** penalty when a fault (e.g. leaking cooling valve) fights heating.

This is **not** calibrated M&V—just a **teaching** stub for integrators and future optimization layers.

## Assumptions (tune per site)

- `Q_c` = design cooling capacity (**tons**) from the graph (`ofdd:coolingCapacityTons`).
- Valve is leaking cold water / coil active at fraction `f` (0–1), estimated from trend (e.g. `clg_cmd` near 0 but SAT or coil ΔT says otherwise)—**your FDD rule supplies `f`**.
- Simultaneous reheat / heating is on at roughly the same time over `h` hours.
- **Crude electric proxy:** treat unwanted cooling as chiller / compressor load at ~**3.517 kW per ton** (order-of-magnitude; replace with COP/PLR model later).

## Formula (kWh, order-of-magnitude)

\[
E_{\text{extra}} \approx Q_c \times 3.517 \times f \times h
\]

- \(Q_c\) in **tons**, \(h\) in **hours**, result in **kWh** (scale of magnitude for “how big is this fault?”).

**Example:** \(Q_c = 25\) tons, \(f = 0.15\) leak, \(h = 8\) h run → \(25 \times 3.517 \times 0.15 \times 8 \approx 106\) kWh per event window.

## What Open-FDD provides

| Piece | Where |
|-------|--------|
| Design tons / MBH | Equipment **engineering** → RDF `ofdd:coolingCapacityTons`, `ofdd:heatingCapacityMBH` |
| Topology (AHU → VAV) | `brick:feeds` / `brick:isFedBy` + optional `s223:*` |
| BACnet + DB series | `ref:BACnetReference` + `ref:TimeseriesReference` on points; scrape → `timeseries_readings` |
| Fault flag / severity | YAML FDD rules → `f` or duration `h` from fault analytics |

## Next steps (product / integration)

- Pull `Q_c` with SPARQL (see `sparql_engineering_examples.md`).
- Pull average `clg_cmd` / SAT for the fault window from SQL or API download CSV.
- Replace 3.517 with **site COP** or **utility $/kWh** for cost.
