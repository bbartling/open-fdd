# Verify React context menus

## Build check

```bash
node --check frontend/app.js
```

## Manual UI test

1. Open `http://<host>:8080` and log in (agent/integrator).
2. Right-click a **BACnet/IP** driver row → menu with Refresh, Scan overrides, Export CSV.
3. Right-click **device 5007** → Copy address, Copy instance, Filter to device.
4. Right-click a **point** → Copy point id, Read priority array (live), View raw JSON in drawer.
5. Press **⋮** on any row → same menu (keyboard/accessibility fallback).
6. Press **Escape** → menu closes.
7. Click outside menu → menu closes.
8. Confirm no `alert(JSON.stringify(...))` popups for normal actions.

## Modbus / JSON / Haystack

Repeat context menu checks on Modbus device/point, JSON API source, and Haystack site rows.

## Details drawer

Select “View raw JSON” or click a point → drawer opens with Raw JSON and Protocol tabs, Copy button, validation warnings if present.
