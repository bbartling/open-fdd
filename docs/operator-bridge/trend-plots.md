# Trend plots

The **Trend plot** tab reads feather historian data via `GET /api/timeseries/readings`.

## HTTP / Tailscale

Charts work over plain HTTP on localhost, LAN, and Tailscale — COOP/CORP security
headers are omitted on non-HTTPS origins so Plotly is not blocked.

## Troubleshooting

If the chart is blank, open **Trend plot debug** at the bottom of the tab:

- Endpoint called
- Site, equipment, selected keys
- Series and timestamp row counts
- Last error message

Common fixes: enable BACnet polling, pick points with feather columns, reduce FDD overlay scope.
