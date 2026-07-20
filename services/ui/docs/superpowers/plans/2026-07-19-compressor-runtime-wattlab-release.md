# Vibe 19 Compressor Runtime and WattLab Release Implementation Plan

> **Status (2026-07-19):** Tasks 1–7 are implemented and validated on
> `fix/vibe19-compressor-runtime-and-wattlab-export` (PR to `develop`). Task 8
> (browser / Docker / PR / GHCR) is the remaining release gate. Historical
> `- [ ]` checkboxes below are the original execution audit trail — do **not**
> treat unchecked boxes as unfinished product work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver trustworthy multi-device compressor runtime analytics, a compact WattLab dump v3, validated Streamlit/Docker behavior, and the final established Vibe 19 GHCR release.

**Architecture:** Keep `app.analytics` and existing CSV names as compatibility surfaces while adding a focused interval-duration module and explicit series/coverage semantics. WattLab exports use CSV v3 profiles and one shared telemetry file per equipment instead of duplicating telemetry for every rule result.

**Tech Stack:** Python 3.11+, pandas, NumPy, Plotly, Streamlit, pytest, Playwright (manual browser validation), Docker Buildx, GitHub Actions/GHCR.

## Global Constraints

- Cooling valves never prove compressor runtime.
- A mapped compressor device with zero observed runtime is eligible, not excluded.
- Device-hours and any-active hours are distinct semantic series.
- Aggregate traces are never stacked with individual devices and are never deduplicated by equal values.
- Existing CSV filenames and legacy columns remain available.
- WattLab `summary` is the default profile.
- Vibe 20 remains the EnergyPlus consumer; no Vibe 20 container is published.
- Publish Vibe 19 only through `.github/workflows/vibe19-ghcr.yml`.
- Merge only after tests, browser validation, local Docker validation, PR checks, and review are green.

---

### Task 1: Timestamp-Duration Foundation

**Files:**
- Create: `app/runtime_intervals.py`
- Test: `tests/test_runtime_intervals.py`
- Modify: `app/rules/base.py`

**Interfaces:**
- Produces: `interval_durations(index, *, nominal_seconds, max_gap_seconds=None, final_duration_seconds=0.0) -> pd.Series`
- Produces: `hours_under_mask(mask, *, nominal_seconds, max_gap_seconds=None) -> float`
- Consumed by: mechanical-cooling per-device and aggregate calculations.

- [ ] **Step 1: Write failing duration tests**

```python
def test_interval_durations_sorts_deduplicates_and_caps_gaps():
    idx = pd.DatetimeIndex([
        "2026-07-01T00:10:00Z",
        "2026-07-01T00:00:00Z",
        "2026-07-01T00:10:00Z",
        "2026-07-01T04:00:00Z",
    ])
    result = interval_durations(
        idx, nominal_seconds=600, max_gap_seconds=1800
    )
    assert result.index.is_monotonic_increasing
    assert result.index.is_unique
    assert result.tolist() == [600.0, 1800.0, 0.0]


def test_hours_under_mask_does_not_credit_final_row_or_large_gap():
    idx = pd.to_datetime([
        "2026-07-01T00:00:00Z",
        "2026-07-01T00:10:00Z",
        "2026-07-01T05:00:00Z",
    ])
    mask = pd.Series([True, True, True], index=idx)
    assert hours_under_mask(
        mask, nominal_seconds=600, max_gap_seconds=1800
    ) == pytest.approx(40 / 60)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_runtime_intervals.py -q`

Expected: import failure because `app.runtime_intervals` does not exist.

- [ ] **Step 3: Implement deterministic interval utilities**

```python
def interval_durations(
    index: pd.Index,
    *,
    nominal_seconds: float,
    max_gap_seconds: float | None = None,
    final_duration_seconds: float = 0.0,
) -> pd.Series:
    if not isinstance(index, pd.DatetimeIndex) or index.empty:
        return pd.Series(dtype=float)
    clean = pd.DatetimeIndex(index).drop_duplicates().sort_values()
    seconds = clean.to_series().shift(-1).sub(clean.to_series()).dt.total_seconds()
    cap = (
        float(max_gap_seconds)
        if max_gap_seconds is not None
        else max(float(nominal_seconds) * 3.0, float(nominal_seconds))
    )
    seconds = seconds.clip(lower=0.0, upper=cap)
    if len(seconds):
        seconds.iloc[-1] = max(float(final_duration_seconds), 0.0)
    return seconds.astype(float)


def hours_under_mask(
    mask: pd.Series,
    *,
    nominal_seconds: float,
    max_gap_seconds: float | None = None,
) -> float:
    normalized = mask.groupby(level=0).max().sort_index().fillna(False).astype(bool)
    durations = interval_durations(
        normalized.index,
        nominal_seconds=nominal_seconds,
        max_gap_seconds=max_gap_seconds,
    )
    return float((normalized.reindex(durations.index).astype(float) * durations).sum() / 3600.0)
```

- [ ] **Step 4: Replace private rule duration duplication**

Make `app.rules.base._sample_deltas_seconds` delegate to
`interval_durations`, retaining the rule API's existing last-sample behavior
where needed by confirmation logic. Mechanical cooling always uses a zero final
duration.

- [ ] **Step 5: Run focused and rule-duration regression tests**

Run: `python -m pytest tests/test_runtime_intervals.py tests/test_confirm_and_duration.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

Commit message: `refactor: add trustworthy interval duration utilities`

---

### Task 2: Compressor Eligibility, Proof, and Aggregate Semantics

**Files:**
- Modify: `app/analytics.py`
- Modify: `app/column_map_json.py`
- Modify: `app/site_model.py`
- Test: `tests/test_analytics.py`
- Test: `tests/test_mech_cooling_domain.py`

**Interfaces:**
- `mech_cooling_run_mask(...) -> tuple[pd.Series | None, str]` remains compatible.
- `mech_cooling_coverage(...) -> pd.DataFrame` gains normalized domain columns.
- `mech_cooling_oat_bins(...) -> pd.DataFrame` gains explicit series rows.
- New internal result: `_mechanical_cooling_devices(...) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write classification/proof tests**

Cover direct chiller status, analog chiller power threshold, eligible flat-zero
chiller, chilled-water AHU exclusion, DX AHU, two-stage RTU unit-active OR
semantics, heat pump heating-only exclusion, heat pump cooling inclusion,
missing proof, analog noise, and VRF outdoor compressor status.

```python
def test_flat_zero_chiller_is_eligible_no_runtime():
    coverage = mech_cooling_coverage(
        {"CHILLER_1": typed_frame("CHW_PLANT", chiller_status=[0, 0, 0])},
        role_map={},
    )
    row = coverage.iloc[0]
    assert row["eligibility_state"] == "eligible_no_runtime"
    assert row["included"]
    assert row["runtime_hours"] == 0


def test_heat_pump_heating_mode_does_not_count_as_cooling():
    frame = typed_frame(
        "HP",
        compressor_status=[1, 1, 1],
        heat_pump_cooling_status=[0, 0, 0],
    )
    mask, _ = mech_cooling_run_mask(frame, equipment_type="HP")
    assert mask is not None
    assert not mask.any()
```

- [ ] **Step 2: Run classification tests and verify RED**

Run: `python -m pytest tests/test_mech_cooling_domain.py -q`

Expected: failures for normalized states, mode gating, stage roles, and VRF type.

- [ ] **Step 3: Formalize proof ladders and metadata**

Add canonical roles for compressor stages, compressor command, compressor/chiller
power/current, heat-pump cooling mode, unit cooling status, and VRF outdoor
status. Proof selection returns a zero-valued boolean mask when a valid mapped
proof exists but never turns on; only absence/invalid data returns `None`.

The coverage row includes:

```python
{
    "equipment_id": equipment_id,
    "equipment_type": equipment_type,
    "cooling_technology": cooling_technology,
    "compressor_based": compressor_based,
    "included": included,
    "eligibility_state": eligibility_state,
    "activity_state": activity_state,
    "proof_quality": proof_quality,
    "proof_role": proof_role,
    "proof_column": proof_column,
    "proof_threshold": proof_threshold,
    "runtime_hours": runtime_hours,
    "valid_elapsed_hours": valid_elapsed_hours,
    "coverage_pct": coverage_pct,
    "exclusion_reason": exclusion_reason,
    # legacy:
    "status": "included" if included else "excluded",
    "proof": proof_role,
    "reason": exclusion_reason,
}
```

- [ ] **Step 4: Write aggregate RED tests**

Test zero devices, one zero-runtime device, one running device, non-overlap,
overlap, three mixed devices, irregular timestamps, duplicate timestamps, large
gaps, missing OAT, and exact OAT-bin boundaries.

```python
def assert_bin_invariants(rows):
    for _, group in rows.groupby("bin_start"):
        individual = group[group.series_kind == "individual_device"].runtime_hours.sum()
        device = group[group.series_kind == "aggregate_device_hours"].runtime_hours.iloc[0]
        active = group[group.series_kind == "aggregate_active_hours"].runtime_hours.iloc[0]
        assert device == pytest.approx(individual)
        assert active <= device + 1e-9
        assert active <= group.valid_elapsed_hours.max() + 1e-9
```

- [ ] **Step 5: Implement individual/device-hours/active-hours rows**

Use interval durations after per-device proof flags. Align active devices on a
union interval index and calculate any-active as a boolean OR. Add:

```python
series_kind = Literal[
    "individual_device",
    "aggregate_device_hours",
    "aggregate_active_hours",
]
```

Retain `equipment_id="ALL"` and `source_kind="total"` for device-hours only.
Use `series_id="aggregate_active_hours"` for active-hours.

- [ ] **Step 6: Run domain, analytics, and golden tests**

Run:
`python -m pytest tests/test_runtime_intervals.py tests/test_mech_cooling_domain.py tests/test_analytics.py tests/test_analytics_golden.py -q`

Expected: all pass; update analytics golden only after reviewing intentional
schema/value changes.

- [ ] **Step 7: Commit**

Commit message: `fix: model compressor runtime and active-hour aggregates`

---

### Task 3: Plotly and Streamlit Mechanical-Cooling UX

**Files:**
- Modify: `app/charts.py`
- Modify: `streamlit_app.py`
- Test: `tests/test_mech_cooling_plot.py`
- Modify: `tests/test_turnkey_app.py`

**Interfaces:**
- `mech_cooling_oat_histogram(bins_df) -> go.Figure | None`
- New helper: `mech_cooling_runtime_message(coverage) -> str | None`

- [ ] **Step 1: Write Plotly figure RED tests**

```python
def test_one_device_figure_keeps_three_semantic_traces():
    fig = mech_cooling_oat_histogram(one_device_rows())
    assert [trace.name for trace in fig.data] == [
        "CHILLER_2",
        "Total compressor device-hours",
        "Any compressor active",
    ]
    assert fig.data[0].type == "bar"
    assert fig.data[1].type == "scatter"
    assert fig.data[2].type == "scatter"
    assert fig.layout.barmode == "stack"
    assert all(trace.showlegend is not False for trace in fig.data)
```

Assert unique descriptive names, required hover fields, aggregates outside the
stack, equal y-values retained, and empty input returns `None`.

- [ ] **Step 2: Run Plotly tests and verify RED**

Run: `python -m pytest tests/test_mech_cooling_plot.py -q`

Expected: aggregate traces are bars and active-hours is absent.

- [ ] **Step 3: Implement mixed bar/line figure**

Individual rows become stacked `go.Bar` traces. Device-hours becomes
`go.Scatter(mode="lines+markers")`; active-hours is dashed. Set explicit
`legendgroup`, stable labels, and custom hover data for proof/count/coverage
metadata.

- [ ] **Step 4: Add coverage states and explanatory copy**

Render all normalized coverage columns with human labels. Display:

```text
Only CHILLER_2 had observed compressor runtime during this period.
Total compressor device-hours therefore equal CHILLER_2 runtime.
```

For zero eligible devices display the required compressor-proof warning.
Eligible zero-runtime rows remain visible as `No runtime observed`.

- [ ] **Step 5: Add AppTest assertions**

Assert no exceptions, required warning/message states, coverage dataframe,
profile selector defaults, and dump profile rerun persistence.

- [ ] **Step 6: Run focused UI tests**

Run:
`python -m pytest tests/test_mech_cooling_plot.py tests/test_turnkey_app.py tests/test_unit_toggle.py -q`

Expected: all pass.

- [ ] **Step 7: Commit**

Commit message: `feat: clarify compressor runtime in Streamlit and Plotly`

---

### Task 4: WattLab Export Profiles and Shared Telemetry

**Files:**
- Modify: `app/wattlab_dump.py`
- Modify: `app/agent_api.py`
- Modify: `scripts/agent_afdd.py`
- Create: `scripts/profile_wattlab_export.py`
- Modify: `streamlit_app.py`
- Create: `tests/test_wattlab_export_profiles.py`
- Modify: `tests/test_wattlab_dump.py`
- Modify: `tests/test_agent_api.py`

**Interfaces:**
- `ExportProfile = Literal["summary", "diagnostic", "forensic"]`
- `export_agent_bundle(..., profile: ExportProfile = "summary", selected_evidence: set[tuple[str, str]] | None = None) -> dict[str, Path]`
- `write_shared_telemetry(frames, role_map, out_dir, *, profile) -> dict[str, Path]`
- `write_fdd_evidence(results, out_dir, *, profile, selected_evidence=None) -> ExportCounts`

- [ ] **Step 1: Write and verify a deterministic baseline profiler**

Add a test for a profiler fixture containing CHW plant, DX AHU, chilled-water
AHU, heat pump, and VAV equipment plus FAULT/PASS/ERROR/skip result statuses.
Implement the fixture/export measurement wrapper without changing production
export behavior, then run:

`python scripts/profile_wattlab_export.py --mode current --out .artifacts/wattlab_export_before.json`

The baseline JSON must contain elapsed seconds, file count, compressed and
uncompressed bytes, result-status counts, and per-rule timeseries count. Keep
this artifact for the final report; do not commit generated telemetry/zips.

- [ ] **Step 2: Write profile policy RED tests**

Build results for FAULT, PASS, ERROR, missing-role, equipment-off, and
not-applicable statuses. Assert summary writes no per-rule timeseries;
diagnostic writes FAULT/ERROR/selected evidence; forensic writes applicable
evidence but no known pointless skip files.

```python
def test_summary_suppresses_cartesian_timeseries(tmp_path):
    counts = write_fdd_evidence(all_status_results(), tmp_path, profile="summary")
    assert list((tmp_path / "fdd_timeseries").glob("*.csv")) == []
    assert counts.suppressed_status["NOT_APPLICABLE_EQUIPMENT_TYPE"] == 1
    assert counts.suppressed_status["SKIPPED_MISSING_ROLES"] == 1
    assert counts.suppressed_status["SKIPPED_EQUIPMENT_OFF"] == 1
```

- [ ] **Step 3: Run profile tests and verify RED**

Run: `python -m pytest tests/test_wattlab_export_profiles.py -q`

Expected: missing profile APIs and current broad serialization.

- [ ] **Step 4: Implement explicit allowlist policy**

Create profile constants and a frozen `ExportCounts` dataclass. Existing
`write_fdd_timeseries` delegates to the profile-aware writer for compatibility.
Never serialize non-applicable/missing-role/equipment-off time series.

- [ ] **Step 5: Write shared telemetry RED tests**

Assert one telemetry file per equipment, deterministic filenames/order, mapped
roles only in summary, broader raw columns in forensic, one timestamp column,
and evidence metadata references the shared path rather than copying telemetry.

- [ ] **Step 6: Implement shared CSV telemetry**

Write `telemetry/<equipment_slug>.csv`. Summary keeps timestamp plus mapped
roles needed by model seed/runtime/fault evidence. Diagnostic includes evidence
columns. Forensic includes broad processed telemetry subject to existing
privacy/package constraints.

- [ ] **Step 7: Expose profiles**

Add `--export-profile {summary,diagnostic,forensic}` to `scripts/agent_afdd.py`.
Add a Streamlit selectbox defaulting to Summary and pass it through
`_build_wattlab_dump_zip(profile=...)`. Persist profile in the manifest.

- [ ] **Step 8: Run export/API/UI tests**

Run:
`python -m pytest tests/test_wattlab_export_profiles.py tests/test_wattlab_dump.py tests/test_agent_api.py tests/test_turnkey_app.py -q`

Expected: all pass.

- [ ] **Step 9: Commit**

Commit message: `feat: add compact WattLab export profiles`

---

### Task 5: Sensor Statistics, Manifest Metrics, and Performance Evidence

**Files:**
- Modify: `app/wattlab_dump.py`
- Modify: `app/agent_api.py`
- Modify: `scripts/profile_wattlab_export.py`
- Create: `tests/test_wattlab_performance_contract.py`
- Modify: `tests/test_wattlab_dump.py`

**Interfaces:**
- `sensor_stats_tables` retains existing keys and adds required columns.
- Manifest schema is `wattlab_dump_v3`.
- `profile_wattlab_export.py --out <json>` writes before/after comparable metrics.

- [ ] **Step 1: Write expanded statistics RED tests**

Assert count, valid count, missing percentage, duration, min/max/mean/std,
p01/p05/p25/p50/p75/p95/p99, occupied/unoccupied, fan-on/off,
weekday/weekend, flatline/out-of-range, units/source/equipment/start/end, and
model-seed provenance/confidence fields.

- [ ] **Step 2: Run statistics tests and verify RED**

Run: `python -m pytest tests/test_wattlab_dump.py -q`

Expected: missing v3 statistics fields.

- [ ] **Step 3: Implement additive statistics**

Keep legacy `n`, quartiles, and mean columns. Add fields rather than renaming
existing columns. Calculate durations with `interval_durations`.

- [ ] **Step 4: Add export timing/count instrumentation**

Use `time.perf_counter()` around rule execution (where called), analytics,
telemetry/evidence serialization, and zip compression. Manifest/run report
include status counts, result count, applicable count, emitted/suppressed file
counts, bytes, and stage seconds.

- [ ] **Step 5: Add deterministic performance harness**

The script exports the same synthetic multi-equipment fixture used by the saved
pre-change baseline, measures the v3 summary directory/zip, and writes JSON
with:

```json
{
  "runtime_seconds": {"before": 0.0, "after": 0.0},
  "file_count": {"before": 0, "after": 0},
  "compressed_bytes": {"before": 0, "after": 0},
  "uncompressed_bytes": {"before": 0, "after": 0},
  "per_rule_timeseries": {"before": 0, "after": 0},
  "suppressed_combinations": 0
}
```

- [ ] **Step 6: Add semantic performance guard**

Assert summary file count is below the rule/equipment Cartesian-product count,
skip statuses emit no timeseries, sensor/setpoint/model-seed artifacts remain,
and Vibe 20-required tables exist. Do not assert a fragile wall-clock speedup.

- [ ] **Step 7: Run performance contract**

Run:
`python -m pytest tests/test_wattlab_performance_contract.py tests/test_wattlab_dump.py -q`

Run:
`python scripts/profile_wattlab_export.py --mode summary --baseline .artifacts/wattlab_export_before.json --out .artifacts/wattlab_export_after.json`

Expected: tests pass and JSON contains measured before/after values from the
same fixture, including removed per-rule files and suppressed combinations.

- [ ] **Step 8: Commit**

Commit message: `perf: deduplicate WattLab evidence and record export metrics`

---

### Task 6: Vibe 20 Compatibility and Documentation

**Files:**
- Modify: `../vibe_code_apps_20/wattlab/seed/bundle.py`
- Create: `../vibe_code_apps_20/tests/test_seed_bundle_v3.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `vibe19_agent_spec/AGENTS.md`
- Modify: `vibe19_agent_spec/docs/ANALYTICS.md`
- Modify: `vibe19_agent_spec/SESSION_LOG.md`
- Modify: `docs/PACKAGE_SPEC.md`
- Modify: `docs/DOCKER.md`

**Interfaces:**
- Vibe 20 `load_bundle` continues accepting v2 and accepts v3.
- `SeedBundle` exposes manifest/profile and shared telemetry paths without
  loading all telemetry eagerly.

- [ ] **Step 1: Write Vibe 20 compatibility RED tests**

Create minimal v2 and v3 zip fixtures at test runtime. Assert both load, new
mechanical tables preserve rows/columns, summary profile works without
`fdd_timeseries`, and telemetry paths are discoverable lazily.

- [ ] **Step 2: Run compatibility test and verify RED**

Run from `vibe_code_apps_20`:
`python -m pytest tests/test_seed_bundle_v3.py -q`

Expected: v3 telemetry/profile discovery assertions fail.

- [ ] **Step 3: Implement additive Vibe 20 loading**

Read manifest schema/profile, index `telemetry/*.csv`, retain optional legacy
`fdd_timeseries_dir`, and do not require either evidence layout.

- [ ] **Step 4: Update documentation**

Document compressor-only semantics, proof quality, zero-runtime eligibility,
device-hours versus active-hours, one-device equality, cooling-valve exclusion,
v3 migration, profiles/default behavior, statistics/provenance, and final GHCR
tags/pull instructions.

- [ ] **Step 5: Run focused cross-app tests**

Run from repository root:

`python -m pytest vibe_code_apps_19/tests/test_wattlab_export_profiles.py vibe_code_apps_20/tests/test_seed_bundle_v3.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

Commit message: `docs: document compressor runtime and WattLab v3 handoff`

---

### Task 7: Full Automated and BUILDING_100 Verification

**Files:**
- Modify if needed: `tests/test_analytics_golden.py`
- Create: `.artifacts/` outputs only (gitignored)

**Interfaces:**
- No product API changes.

- [ ] **Step 1: Run full Vibe 19 test suite**

Run from `vibe_code_apps_19`: `python -m pytest -q`

Expected: zero failures.

- [ ] **Step 2: Run affected Vibe 20 tests**

Run from `vibe_code_apps_20`:
`python -m pytest tests/test_seed.py tests/test_seed_bundle_v3.py tests/test_twin.py -q`

Expected: zero failures.

- [ ] **Step 3: Locate and run BUILDING_100 optional integration**

Use `VIBE19_TEST_PACKAGE_DIR` when provided or the documented local fixture.
Run:
`python -m pytest -m optional_zip tests/test_analytics_golden.py tests/test_agent_api.py -q`

Verify Chiller 1 eligible/no-runtime, Chiller 2 runtime, AHU valves excluded,
both aggregates present, device-hours equal Chiller 2 where it is sole-running,
and bin totals reconcile.

- [ ] **Step 4: Run AppTest and smoke scripts**

Run:
`python scripts/smoke_streamlit_app.py`

Run:
`python -m pytest tests/test_turnkey_app.py -q`

Expected: no Streamlit exceptions.

- [ ] **Step 5: Run static diagnostics**

Run: `python -m compileall -q app streamlit_app.py`

Run: `ruff check app tests scripts` if Ruff is available; report pre-existing
diagnostics separately from introduced diagnostics.

- [ ] **Step 6: Commit any evidence-driven corrections**

Use focused fix commits only after adding a reproducing failing test.

---

### Task 8: Real Browser, Docker, PR, Merge, and Final GHCR

**Files:**
- Create: `scripts/browser_smoke_vibe19.py`
- Modify: `pyproject.toml` dev dependencies
- Create: `.artifacts/browser/` screenshots only (gitignored)

**Interfaces:**
- Browser script accepts `--url`, `--package`, and `--screenshots`.

- [ ] **Step 1: Add Playwright browser smoke**

Add Playwright to the dev extra and implement a script that opens the app,
uploads/loads supported demo data, navigates Overview/mechanical cooling,
checks required traces/coverage/explanation, reruns after a filter change,
captures console/page errors, and saves screenshots.

The script or its generated packages must exercise all required visual cases:
one running device, overlapping multiple devices, no eligible compressor,
eligible zero-runtime compressor, and chilled-water AHU valve exclusion.

- [ ] **Step 2: Run native Streamlit browser validation**

Start:
`python -m streamlit run streamlit_app.py --server.headless true`

Run:
`python scripts/browser_smoke_vibe19.py --url http://localhost:8501 --screenshots .artifacts/browser/native`

Check server logs for Traceback/StreamlitAPIException/Plotly/error signatures.

- [ ] **Step 3: Build and run local Docker image**

Run:
`docker build -t vibe19:compressor-runtime-local .`

Run:
`docker run --rm -d -p 8502:8501 --name vibe19-compressor-local vibe19:compressor-runtime-local`

Run browser smoke against `http://localhost:8502`, inspect container logs, then
stop the container.

- [ ] **Step 4: Push branch and open PR**

Push `fix/vibe19-compressor-runtime-and-wattlab-export`. Create one PR to
`develop` containing root cause, behavioral changes, screenshots, tests,
performance table, compatibility notes, and Docker evidence.

- [ ] **Step 5: Resolve CI/review and merge**

Wait for required checks, investigate failures with reproducing tests, address
legitimate review comments, and merge only when green. Confirm merge commit on
`develop`.

- [ ] **Step 6: Watch established Vibe 19 GHCR publish**

Watch `.github/workflows/vibe19-ghcr.yml` triggered by the merge. If cache
references are broken, dispatch `no_cache=true` on `develop`. Do not publish by
another workflow or local push.

- [ ] **Step 7: Verify and pull immutable image**

Run:

```powershell
docker buildx imagetools inspect ghcr.io/bbartling/vibe19:latest
docker pull ghcr.io/bbartling/vibe19:sha-<merge-sha>
docker image inspect ghcr.io/bbartling/vibe19:sha-<merge-sha> --format '{{json .RepoDigests}}'
```

Confirm `linux/amd64` and `linux/arm64`, and record the index/image digest.

- [ ] **Step 8: Run pulled GHCR image and repeat browser smoke**

Run the immutable SHA image on a free host port with the supported demo package
mounted or uploaded. Repeat browser smoke and inspect container logs.

- [ ] **Step 9: Publish exact final report**

Use the requested nine sections:

1. Root Cause
2. Mechanical-Cooling Semantics
3. Files Changed
4. Tests
5. Browser Validation
6. WattLab Performance
7. Docker and GHCR
8. Pull Request and CI
9. Remaining Limitations
