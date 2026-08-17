# Cursor agent prompt — Vibe19 UI deprecations, pandas timestamps, ANY-BAS package contract

Paste this entire file as the first message in a **new Cursor agent chat** whose workspace is:

`C:\Users\ben\Documents\py-bacnet-stacks-playground\vibe_code_apps_19`

Repo: `https://github.com/bbartling/py-bacnet-stacks-playground`. Prefer branch work from **`origin/develop`** (or the vibe19 app path’s default product branch — confirm with `git status` / remote).

Do **not** open or hard-code the Central Heights / Metasys (`sp_jci`) job. This app must stay vendor-agnostic.

---

## Machine split (read this)

| Machine | Owns |
| --- | --- |
| **Windows** (this chat) | Vibe App 19 Streamlit UI, package loaders, Haystack sidecar JSON, AGENTS/mapping docs, playground GH Actions / vibe19 GHCR |
| **Bensbench / open-fdd** | DataFusion Rust ingest, SQL rules, `open_fdd` PyPI oracle, MCP docs — **separate plan** `~/.cursor/plans/openfdd_ts_package_contract_a7c3e91f.plan.md` |

**Do not** patch Open-FDD Rust/SQL/DataFusion from this Windows session. **Do not** `docker build` Open-FDD on bensbench. After vibe19 GHCR publish, Linux only `docker pull`.

Cycles 1–5 FDD leftover dump work is **done on open-fdd**. Do not reopen those SQL PRs here.

You are patching **Vibe App 19** so Streamlit/pandas stop yelling, so Haystack sidecars parse real-world JSON, and so **AGENTS.md + mapping docs** give the next AI agent enough context to preprocess **any** BAS historian into an `openfdd_package_v1` zip.

Charts, FDD plots, RCx, motor hours, mixing scatter, and OAT-METEO are **data-model driven**. If roles are missing, the UI warns. The app must **not** invent vendor point names (no `SF-O`, no `GLYCOL_SYSTEM`, no Madison lat/lon) in Python. Site-specific mapping belongs in the **package** the agent builds offline.

Read first: root [`AGENTS.md`](../AGENTS.md), [`docs/PACKAGE_SPEC.md`](PACKAGE_SPEC.md), [`docs/HAYSTACK_LIKE_MAPPING_GUIDE.md`](HAYSTACK_LIKE_MAPPING_GUIDE.md), [`docs/DATA_MODEL_DRIVEN.md`](DATA_MODEL_DRIVEN.md), [`docs/COLUMN_MAP_JSON.md`](COLUMN_MAP_JSON.md).

## Non-negotiable

1. **No site/vendor hardcoding** in `app/` — not Johnson Controls, ALC, Niagara, BACnet, a school name, a city, or a single equipment id. Lat/lon for Open-Meteo stays a **caller argument** (`app/open_meteo.py` already works that way).
2. **Do not fork OpenFDD equations.** Do not add Rust/DataFusion.
3. Gold fixtures must still load: `tests/fixtures/`, Building 100 style maps, synthetic 59-rule zip if present on disk. Add tests; do not weaken existing ones.
4. `python -m pytest -q` (or `.\scripts\run_tests_local.ps1`) before claiming done.
5. **Do not commit** unless the human asks. When asked to land: squash-merge to `develop`, delete the branch, leave CI green.

## Phase A — Streamlit `use_container_width` deprecation

Streamlit will remove `use_container_width` after **2025-12-31**.

- `True` → `width="stretch"`
- `False` → `width="content"`

Grep the **whole repo** (`*.py`), not only the three files that already warned:

- `streamlit_app.py`
- `app/ui_vav_health.py`
- `app/report_downloads.py` (`report_download_button` kwarg + `st.download_button`)

Replace every `use_container_width=...` on Streamlit widgets. If a helper still takes `use_container_width: bool`, rename it to `width` or map bool → `"stretch"` / `"content"` so callers stay clean.

`requirements.txt` is `streamlit>=1.28`. If `width=` is too new for 1.28, gate with `hasattr` / version check **or** bump the Streamlit floor in requirements to a version that documents `width=` (prefer bump + one comment in AGENTS.md). Do not leave deprecation spam on current Streamlit 1.4x/1.5x.

## Phase B — Pandas `Could not infer format` on `timestamp_utc`

`pd.to_datetime(..., utc=True)` without `format=` warns on ISO-8601 **`Z`** suffixes (`2026-05-21T20:20:00Z`) and on mixed `Z` vs `+00:00`. Both are valid UTC. Gold fixtures often use `+00:00`; many BAS exports use `Z`.

Fix the **loader**, not a single building’s CSV:

- `app/package_io.py` (~line 878, `_validate_equipment_csv`)
- `app/data_loader.py` (~line 30, `normalize_timestamp`)
- Also grep: `app/data_contract.py`, `app/source_profile.py`, `app/open_meteo.py`, `shared/validate_hvac_data.py`, `scripts/gen_openfdd_building_maps.py`

Use `format="ISO8601"` (pandas 2.x) with `utc=True`, `errors="coerce"`. If a frame still fails, fall back to `format="mixed"` then dateutil — **once**, not per-row warnings.

Add a tiny unit test: parse a Series containing **both** `...Z` and `...+00:00` with **zero** `UserWarning` from pandas (use `pytest.warns` / `warnings.catch_warnings`). Do not require packages to rewrite timestamps; the app must accept both.

Note: Open-FDD PyPI / Rust ingest may get a parallel ISO8601 + no-epoch-zero patch on bensbench — **do not duplicate that work here**. Keep Vibe19 loaders self-contained.

## Phase C — Sidecar JSON robustness (any Haystack-shaped map)

`app/sidecar_maps.py` `_points_from_payload` treats **any** key named `equip` as a **full package map**. Haystack-style single-equip JSON often has `"equip": "AHU_1"` as a **string device id**. That currently raises:

`package-style map has no points/column_roles for this equipment`

Fix: only take the package-map branch when `equip` / `equipment` / `devices` is a **dict** (or list of blocks). If `equip` is a string, ignore it as metadata and read `points` / `column_roles` like a single-equip sidecar.

Add a test with `{equipType, equipment_type, device, equip: "<string>", points: {...}}`.

(Open-FDD Rust `points_from_map_json` already requires an object — do not “port” Rust; just fix Python.)

## Phase D — Butter up agent docs (this is the product)

Expand **root `AGENTS.md`**, [`docs/HAYSTACK_LIKE_MAPPING_GUIDE.md`](HAYSTACK_LIKE_MAPPING_GUIDE.md), and [`docs/DATA_MODEL_DRIVEN.md`](DATA_MODEL_DRIVEN.md) so an AI agent can author a zip for **any** BAS job without reading this chat.

Write as **generic rules**, with examples that use `AHU_1` / `VAV_1` / `CHW_1` / `weather/` — never a real campus.

Must include all of the following.

### D1. Analytics are role-driven

If a chart is empty, the package is missing Haystack **roles**, not “the app is broken.” Empty motors / mixing / VAV / compressor bins are expected when roles are absent. The agent’s job is to map or synthesize columns **in the zip**.

### D2. Stamp types — do not rely on folder names

`equipType` / `equipment_type` is canonical (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`; `rtu`→AHU). Folder `JRH-RM717-VMA-…` will be **UNKNOWN** if unstamped. Unit ventilators / FCUs with air-side points should be typed **`ahu`** unless a cookbook type exists. Chillers → **`chwPlant`**.

### D3. Web weather (Open-Meteo) — package sidecar, not app config

- Put `weather/history_wide.csv` **inside the building root** (never treated as equipment).
- Required analysis column: **`web-outside-air-temp`** (°F). Optional: `web-outside-air-humidity`, dewpoint (app can derive wet-bulb).
- Align to the same UTC grid as HVAC (`timestamp_utc`).
- Fetch with **job lat/lon** (geocode the site). Do not bake a city into Vibe19.
- `session_config.prefer_web_oat: true` — web OAT is primary for economizer / RCx / physics; BAS `outside-air-temp` is for OAT-METEO overlay **only when both exist**.
- BAS OA is often **one site-global sensor** (boiler/plant). Copy that series onto air handlers as `outside-air-temp` in the **package**. The app will not guess which boiler owns OA.

### D4. Fan / pump / tower motor proof

Motors need **`fan-status`** (or pump/tower status), not speed-only leftovers.

When the BAS has **no binary status**:

- Map analog speed/command as **`fan-cmd`** (0–100% or 0–1).
- **Synthesize** a 0/1 column in the wide CSV (e.g. `fan_s = 1` when speed ≥ documented threshold, typically 5% or 0.05).
- Map `fan-status` → that column.
- Same pattern for pumps/towers from VFD % or proven loop DP — **document the rule in the site preprocess repo**, not in Vibe19 source.
- Never invent motor hours from leave temperature.

### D5. Compressor proof ≠ valve ≠ pump

Mech-cooling OAT bins accept `chiller-status` / `compressor-status` / verified cmd / amps / power. **Never** CHW pump or AHU `cooling-valve`. Optional inferred CHW leave-temp is a **sidebar** on the app, not a silent default.

If the plant only has % cooling output, synthesize `chiller-status` in the package (threshold documented). Map CHW supply/return temps to `chilled-water-supply-temp` / `chilled-water-return-temp`.

### D6. VAV / zone

`zone-airflow` must be **actual CFM**, never the airflow **setpoint**. `zone-air-temp` from the zone sensor. Box damper → `damper`. Reheat → `reheat-valve`. Stamp `vav`.

### D7. Mixing scatter

Needs an AHU/RTU with `fan-status` (or cmd-derived status) **on**, plus `outside-air-temp`, `return-air-temp`, `mixed-air-temp`, and enough `|OAT−RAT|≥10°F` samples. Missing any role → skip, don’t crash.

### D8. Pandas-happy zip hygiene

- `timestamp_utc` ISO-8601 UTC (`Z` or `+00:00` — both OK after Phase B)
- UTF-8 wide CSV, one point per column
- Sibling Haystack JSON **without** using string `equip` as a nested package map (or after Phase C either shape works)
- Forward-slash zip arcnames (Python `zipfile`, never `Compress-Archive`)
- `weather/` nested under the building folder
- Stay under `OPENFDD_MAX_EQUIPMENT` (default 100) or split packages

### D9. What Vibe19 must never grow

No `if building == …`, no Metasys suffix table in `app/`, no default Madison weather, no “glycol” special case. Vendor dictionaries live in **per-job preprocess** (the agent that builds the zip).

## Phase E — Verify

- Grep: no remaining `use_container_width` on Streamlit calls (helpers OK only if they translate to `width=`).
- Tests: datetime Z/+00:00; sidecar `equip` string; existing package/load tests.
- Docs: AGENTS.md section “Package authoring (any BAS job)” plus mapping-guide subsections for weather, synthetic motor proof, compressor vs pump, VAV airflow vs SP.
- `python -m pytest -q`

## Phase F — Turnkey playground closeout (required before “done”)

Do this **after** Phases A–E are green locally. Goal: no stale product debt left for the next agent.

```powershell
cd C:\Users\ben\Documents\py-bacnet-stacks-playground
git fetch origin --prune
git checkout develop
git pull origin develop
gh pr list --state open --limit 30
gh run list --status failure --limit 40
git branch -r
```

1. Land **this** vibe19 patch on `develop` only when the human asks to commit/PR — squash-merge, **delete the branch**.
2. Triage other open playground PRs (`gh pr list`): merge if already green and in-scope, or close with a one-line reason if superseded. Known prior noise: vibe22 RL/docs PRs — do not expand into long RL campaigns unless the human asks; prefer close or park.
3. Rerun or fix **failed** Actions on `develop` / the merge SHA until the product workflows that matter for vibe19 are green (or explicitly waived in the summary).
4. Delete merged remote branches (`git push origin --delete …` / `gh pr view --json headRefName`).
5. If vibe19 GHCR publish is part of your workflow, confirm `ghcr.io/bbartling/vibe19:latest` (or the repo’s documented tag) is pullable — **do not** build Open-FDD images here.
6. Summarize: files changed, PR URL(s), remaining open PRs (ideally zero for vibe19), failed runs cleared.

When done, summarize files changed. Do not commit unless asked — then follow Phase F.
