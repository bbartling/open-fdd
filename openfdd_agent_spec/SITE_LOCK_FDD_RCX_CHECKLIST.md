# Site lock / FDD / RCx / Actions checklist

Do not weaken [`SESSION_LOG.md`](SESSION_LOG.md). These were implied; they are now laws.

1. `?site=` (and `eq`) survive every SectionTabs change (`hrefWithSession`).
2. FDD / RCx / Results / WattLab have **no** Building select — locked `zip:` caption only.
3. FDD last y-axis title is `fault`; `confirmed_fault` is the last trace; fault domain `[0] < 0.4`.
4. Missing overlay after a successful rule run is a **test failure**, not an accepted banner.
5. RCx mocked presets include every `REQUIRED_RCX_PRESET_IDS` id; family order is `RCX_FAMILY_ORDER` (Zones first).
6. Heat pump / Weather families exist as empty placeholders.
7. Actions UI requests `limit=10`; DELETE one + clear-all exist; JSONL cap is 50.
8. Overview: `oracle-hero` does **not** contain `section-tabs`; tabs come **after** `overview-equipment-select`.
9. Demo only after `scripts/openfdd_demo_gate.sh --local-web` — never paste GHCR `sha-a2cca15` Caddy as if it were this branch.
10. Sidebar Active site writes `?site=`; empty URL site must not look selected.
