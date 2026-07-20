# Mechanical-Cooling Proof and Complete Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit hard-status versus CHW-temperature chiller proof mode, always-visible device coverage, and guaranteed full-cookbook WattLab exports.

**Architecture:** Extend the existing analytics functions with one boolean proof-mode input and return coverage runtime metadata without changing strict defaults. Persist the mode in session config, wire one sidebar checkbox to both Overview and agent export, and force the export builder to call the complete rule runner every time.

**Tech Stack:** Python 3.12+, pandas, Streamlit, Plotly, pytest.

## Global Constraints
- Hard status proof remains the default.
- Temperature proof is explicit, CHW-plant-only, and labeled inferred.
- CHW valve position never proves compressor runtime.
- `ALL` remains summed device-hours.
- WattLab export always contains the complete active cookbook run.
- Update `vibe19_agent_spec` and publish the multi-arch vibe19 GHCR image.

---

### Task 1: Analytics proof mode and coverage metadata

**Files:**
- Modify: `app/analytics.py:886-1143`
- Test: `tests/test_analytics.py:82-138`

**Interfaces:**
- `mech_cooling_run_mask(..., use_status_proof: bool = True) -> tuple[pd.Series | None, str]`
- `mech_cooling_coverage(..., use_status_proof: bool = True) -> pd.DataFrame`
- `mech_cooling_oat_bins(..., use_status_proof: bool = True) -> pd.DataFrame`

- [x] Write tests proving strict mode excludes flat-zero CHILLER_1 and temperature mode includes it as `inferred: chw_leave_temp` with threshold-dependent hours.
- [x] Run the focused tests and verify the new assertions fail because the parameter/metadata do not exist.
- [x] Implement the explicit mode. In temperature mode, CHW plants use `_chw_temp_proof`; AHU/HP keep DX proof. Add `runtime_hours` and warning/reason fields to coverage.
- [x] Run focused analytics tests and confirm green.

### Task 2: Sidebar mode, session round-trip, and Overview table

**Files:**
- Modify: `streamlit_app.py:180-200, 390-420, 1939-2002, 2299-2417`
- Modify: `app/package_io.py:168-205, 890-905`
- Modify: `app/agent_api.py:90-116, 360-395`
- Test: `tests/test_unit_toggle.py`
- Test: `tests/test_agent_api.py`
- Test: `tests/test_turnkey_app.py`

**Interfaces:**
- Session key/config field: `use_mech_cooling_status_proof: bool = True`
- Sidebar checkbox key: `use_mech_cooling_status_proof`

- [x] Add failing tests for default checked, slider disabled while checked, enabled while unchecked, config round-trip, and Overview coverage table rendering.
- [x] Run those tests and verify expected failures.
- [x] Add the config field, checkbox, slider disabled parameter, analytics propagation, and always-visible coverage dataframe with inferred warning copy.
- [x] Run the focused UI/config tests and confirm green.

### Task 3: Complete cookbook export guarantee

**Files:**
- Modify: `streamlit_app.py:421-465`
- Test: `tests/test_turnkey_app.py` or a focused export helper test

**Interfaces:**
- `_build_wattlab_dump_zip()` always calls `run_rules(dataset)` and replaces `st.session_state.batch_results`.

- [x] Add a failing regression test that seeds partial `batch_results` and verifies the export invokes/contains a complete run.
- [x] Run the test and verify it fails because existing results are reused.
- [x] Remove the partial-result reuse path and always run the complete cookbook immediately before export.
- [x] Run export tests and confirm green.

### Task 4: Agent specification and verification

**Files:**
- Modify: `vibe19_agent_spec/docs/ANALYTICS.md`
- Modify: `vibe19_agent_spec/SESSION_LOG.md`
- Modify as needed: `README.md`, `AGENTS.md`

- [x] Document proof modes, inferred-temperature warning, always-visible coverage, device-hour aggregation, and complete export semantics.
- [x] Run `python -m pytest tests/test_analytics.py tests/test_unit_toggle.py tests/test_agent_api.py tests/test_wattlab_dump.py tests/test_turnkey_app.py -q`.
- [x] Run the full vibe19 suite.
- [ ] Commit and push `develop`.
- [ ] Watch `.github/workflows/vibe19-ghcr.yml` through successful amd64+arm64 publication and report the run URL.
