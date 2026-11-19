"""Portable hook fixtures must stay generated, SI-only and equal to SQL twins."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/nf/build_sql_analytics_fixtures.py'
spec = importlib.util.spec_from_file_location('analytics_fixture_builder', SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
CASES = json.loads(builder.OUT.read_text(encoding='utf-8'))['cases']


def test_generator_check_and_stale_detection(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--check'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    stale = tmp_path / 'stale.json'
    stale.write_text('{}\n', encoding='utf-8')
    result = subprocess.run([sys.executable, str(SCRIPT), '--check', '--output', str(stale)], capture_output=True)
    assert result.returncode == 1
    assert stale.read_text() == '{}\n'


def test_dst_gap_and_missing_weather_are_observable():
    cases = {case['id']: case for case in CASES}
    runtime = cases['runtime-dst-week-gap-percent-command']
    starts = runtime['options']['week_starts']
    assert (starts[1] - starts[0]) / 3_600_000 == 167
    row = next(r for r in runtime['expected']['rows'] if r['equipment_id'] == 'equipment-1')
    assert row['hours'] == 165
    assert row['in_hours'] + row['after_hours'] == row['hours']
    assert cases['web-weather-empty']['expected']['equipment-1']['mae'] is None
    assert cases['web-weather-outage']['expected']['equipment-1']['n'] == 15
    assert cases['economizer-missing-mat']['expected']['skipped'][0]['reason'] == 'missing_MAT'


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_expected_is_pandas_oracle(case):
    assert builder.expected(case) == case['expected']


@pytest.mark.parametrize('engine', ['sqlite', 'duckdb'])
@pytest.mark.parametrize('case', [c for c in CASES if c['tool'] in
    ('motor_run_hours_weekly', 'mech_cooling_oat_bins', 'economizer_free_cooling_diagnostics')], ids=lambda c: c['id'])
def test_fixtures_agree_with_sql(case, engine):
    if engine == 'duckdb':
        pytest.importorskip('duckdb')
    frames = builder.decode_frames(case)
    roles = case['role_map']
    if case['tool'] == 'motor_run_hours_weekly':
        from open_fdd.analytics.sql_runtime import motor_run_hours_weekly_sql
        options = case['options']
        starts = [pd.Timestamp(t, unit='ms', tz='UTC').tz_convert(options['timezone']) for t in options['week_starts']]
        occupied = [(pd.Timestamp(a, unit='ms', tz='UTC'), pd.Timestamp(b, unit='ms', tz='UTC'))
                    for a, b in options['occupied_intervals']]
        actual = motor_run_hours_weekly_sql(frames, roles, engine=engine, week_starts=starts, occupied_intervals=occupied)
        want = pd.DataFrame(case['expected']['rows'])
        actual['week_start'] = actual['week_start'].map(builder.clean)
        keys = ['equipment_id', 'signal', 'week_start']
        columns = ['hours', 'in_hours', 'after_hours', 'partial_week', 'avg_oat_c']
    elif case['tool'] == 'mech_cooling_oat_bins':
        from open_fdd.analytics.sql_mech_cooling import mech_cooling_oat_bins_sql
        actual = mech_cooling_oat_bins_sql(frames, roles, engine=engine)
        want = pd.DataFrame(case['expected']['rows'])
        keys = ['equipment_id', 'bin_start']
        columns = ['hours', 'runtime_hours', 'valid_elapsed_hours', 'coverage_pct']
    else:
        from open_fdd.analytics.sql_economizer import economizer_metrics_sql
        actual = economizer_metrics_sql(frames, roles, engine=engine)
        want = pd.DataFrame(case['expected']['metrics']['rows'])
        if want.empty:
            assert actual.empty
            return
        keys = ['equipment_id']
        columns = ['fan_on_hours', 'n_fan_on_samples', 'n_identifiable', 'has_damper', 'median_mat_resid_f', 'mat_resid_mae_f']
    pd.testing.assert_frame_equal(actual.sort_values(keys)[keys + columns].reset_index(drop=True),
                                  want.sort_values(keys)[keys + columns].reset_index(drop=True),
                                  check_dtype=False, atol=1e-9, rtol=1e-9)


@pytest.mark.parametrize('engine', ['sqlite', 'duckdb'])
@pytest.mark.parametrize('case', [c for c in CASES if c['tool'] == 'bas_vs_web_oat_stats'], ids=lambda c: c['id'])
def test_weather_fixtures_agree_with_sql(case, engine):
    import sqlite3
    from open_fdd.analytics.sql_anomaly import create_core, load_core
    from open_fdd.analytics.sql_bas_web import run_bas_web_sql
    conn = pytest.importorskip('duckdb').connect(':memory:') if engine == 'duckdb' else sqlite3.connect(':memory:')
    points = [{'site_id': 'local', 'point_key': 'weather', 'equipment_id': None, 'role': 'web_oa_t'}]
    samples = [('local', 'weather', r['ts_ms'], r['value_c']) for r in case['web_weather']]
    for eq, frame in case['frames'].items():
        points.append({'site_id': 'local', 'point_key': eq, 'equipment_id': eq, 'role': 'oa_t'})
        samples += [('local', eq, r['ts_ms'], r['outside-air-temp']) for r in frame['rows']]
    try:
        create_core(conn, engine)
        load_core(conn, engine, points, samples)
        pairs = [(eq, eq, 'weather', int(case['options']['max_age_seconds'] * 1000)) for eq in case['frames']]
        actual = {r['equipment_id']: r for r in run_bas_web_sql(conn, engine, pairs)}
    finally:
        conn.close()
    for eq, want in case['expected'].items():
        if want['n'] == 0:
            assert eq not in actual  # Raw SQL has no paired rows; the hook must retain unassessed/null semantics.
        else:
            assert actual[eq]['n'] == want['n']
            for key in ('bias', 'mae', 'max_abs', 'within_band'):
                assert actual[eq][key] == pytest.approx(want[key], abs=1e-9)
