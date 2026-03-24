# Automated Testing Issues Log

## 2026-03-21

- **2_sparql_crud_and_frontend_test.py**: Fixed the `UnboundLocalError` raised when `--save-report` was used without `--generate-expected`; the function-level `import json` statements shadowed the module import, so JSON report writes failed. Removed the redundant local imports so the global module binding is used everywhere.
- **3_long_term_bacnet_scrape_test.py**: Added automatic site resolution (falls back to the first site on the API when `OFDD_BACNET_SITE_ID`/`--site` is not provided) so downloads/fault checks target `TestBenchSite` instead of the literal string `default`. Wired the fake fault schedule into both the CSV/fault verification and a new `/faults/active` snapshot check so the script now validates that the BACnet fault schedule actually surfaces through the API in real time.
- **4_hot_reload_test.py**: Extended the rules hot-reload test to (optionally) trigger an FDD job per uploaded rule and wait for the generated fault_id to appear in `/faults/state`. Added site auto-detection, a reusable delete helper so test rules are cleaned up even on failure, and a `--skip-fault-verification` escape hatch.
- **Frontend PlotsPage review**: Verified that the current `frontend/src/components/pages/PlotsPage.tsx` no longer contains `selectedDeviceId`, `deviceOptions`, or equipment-scoped fault overlays referenced in CodeRabbit’s nitpicks. No action taken—the hook currently scopes by site (device filtering was removed in this branch).
