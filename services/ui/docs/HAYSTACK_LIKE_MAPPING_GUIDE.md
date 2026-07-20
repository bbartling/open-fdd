# Haystack-like mapping guide (no RDF)

App 19 uses **Project Haystack–style names** for column maps and for rule inputs
(`siteRef`, `equip`, `device`, `equipType`, `points`). It does **not** run Haystack
RDF / Oxigraph / SPARQL.

Rules read the same point names that appear in `points` (for example
`discharge-air-temp`). There is no second vocabulary.

## IDs

| Entity | Haystack-like key | Example |
|--------|-------------------|---------|
| Site | `siteRef` | `campus_a` |
| Building | `building` (folder name) | `HQ_NORTH` |
| Equipment / device | `equip.<id>` + `device` | `AHU_1`, `VAV_7` |
| Equip type | `equipType` | `ahu`, `vav`, `chwPlant`, `boiler`, `heatPump`, `weather` (`rtu` → `AHU`) |
| Point | `points.<haystack-name>` | `discharge-air-temp` |
| Column | CSV header value | `discharge_air_temp_f` |

## Preferred point names

| Haystack point | Typical use |
|----------------|-------------|
| `discharge-air-temp` / `discharge-air-temp-sp` | SAT / SAT SP |
| `mixed-air-temp` / `return-air-temp` / `outside-air-temp` | Mixing envelope |
| `outside-air-damper` | Economizer OA damper % |
| `cooling-valve` / `heating-valve` | Valve % (not mech-cooling OAT-bin proof) |
| `fan-cmd` / `fan-status` | Supply fan |
| `duct-static-pressure` (+ `-sp`) | Duct static |
| `zone-air-temp` / `zone-airflow` / `damper` / `reheat-valve` | VAV / zone |
| `chilled-water-supply-temp` / `chw-pump-status` / `chiller-status` | Plant (pump = motor; `chiller-status` = compressor OAT proof) |
| `compressor-status` / `dx-stage` / `cool-stage` | DX mech-cooling compressor proof |
| `occupied` | Occupancy |
| `web-outside-air-temp` | Open-Meteo / weather CSV |
| `ahu-discharge-air-temp` | Parent AHU SAT copied onto VAV (topology) |

## Topology

Package `vav_to_ahu_simple.csv` defines **VAV fedBy AHU** / **AHU feeds VAVs**.
Shown on the Data Model **Topology** section — not mixed into point tables.

## Authoring

1. Put a sibling `column_map.json` (or `history_wide.json`) next to each equipment CSV, or one package-root map.
2. Prefer Haystack point names in `points`.
3. Values must be exact CSV headers.
4. Stamp `equipType` so rules/analytics do not guess from folder names.

See also: [`COLUMN_MAP_JSON.md`](COLUMN_MAP_JSON.md), [`DATA_MODEL_DRIVEN.md`](DATA_MODEL_DRIVEN.md).
